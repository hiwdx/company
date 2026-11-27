"""Offline fixtures for the on-demand flow. Real filings are checked separately."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from hiwd_company.auto_facts import extract
from hiwd_company.discovery import Cache, Research, Source, SourceUnavailable, directory, query_directory
from hiwd_company.domain import EvidenceError
from hiwd_company.filings import announcement_window, collect_window, periodic_filings
from hiwd_company.reader import read_model
from hiwd_company.parse_worker import parse_in_worker
from hiwd_company.sec import DIRECTORY_URL, SourceResult
from hiwd_company.server import handler_for
from hiwd_company.store import Store, validate_dataset

CIK = '0000001001'
ACC = '0000001001-26-000002'
STAMP = '2026-11-27T09:10:00+00:00'
START, END = '2025-10-01', '2026-09-30'
FILING = {'accessionNumber': ACC, 'filingDate': '2026-11-09', 'reportDate': END, 'form': '10-K', 'primaryDocument': 'new-20260930.htm'}
ISSUER = {'cik': CIK, 'name': 'Unknown Placeholder Stores', 'label': 'Unknown Placeholder Stores',
          'securities': [{'ticker': 'ZZQQ', 'exchange': 'Nasdaq', 'type': 'SEC 挂牌证券'}]}
DIRECTORY = {'fields': ['cik', 'name', 'ticker', 'exchange'],
             'data': [[1001, 'Unknown Placeholder Stores', 'ZZQQ', 'Nasdaq'],
                      [1002, 'Unknown Placeholder Industries', 'ZWQQ', 'NYSE']]}


def financial_document(extra='', metadata_cik=CIK):
    return (f'''<html><ix:header><ix:hidden>
      <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="year">{metadata_cik}</ix:nonNumeric>
      <ix:nonNumeric name="dei:DocumentType" contextRef="year">10-K</ix:nonNumeric>
      <ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="year">FY</ix:nonNumeric>
    </ix:hidden><ix:resources>
      <xbrli:context id="year"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:startDate>{START}</xbrli:startDate><xbrli:endDate>{END}</xbrli:endDate></xbrli:period></xbrli:context>
      <xbrli:context id="end"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>{END}</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    </ix:resources></ix:header>
    <table><tr><th>Total assets</th><td><ix:nonFraction id="portable-asset" name="us-gaap:Assets" contextRef="end" unitRef="usd" scale="6" format="ixt:num-dot-decimal">930</ix:nonFraction></td></tr>
      <tr><th>Total liabilities and equity</th><td>930</td></tr></table>
    <table><tr><th>Revenues</th><td><ix:nonFraction id="portable-sale" name="us-gaap:Revenues" contextRef="year" unitRef="usd" scale="6" format="ixt:num-dot-decimal">615</ix:nonFraction>{extra}</td></tr>
      <tr><th>Income tax expense</th><td>30</td></tr><tr><th>Net income</th><td>160</td></tr>
    </table></html>''').encode()


def companyfacts(*, wrong_amount=False, wrong_accession=False):
    def point(value, start=None):
        return {'end': END, 'filed': FILING['filingDate'], 'form': '10-K', 'val': value,
                'accn': '0000001001-25-000002' if wrong_accession and start else ACC, **({'start': start} if start else {})}
    return {'cik': 1001, 'facts': {'us-gaap': {
        'Assets': {'units': {'USD': [point(930000000)]}},
        'Revenues': {'units': {'USD': [point(999000000 if wrong_amount else 615000000, START)]}},
    }}}


def extracted(html=None, cf=None):
    html = html if html is not None else financial_document()
    cf = cf if cf is not None else companyfacts()
    return extract(ISSUER, FILING, html, cf, observed_at=STAMP,
                   companyfacts_sha256=sha256(json.dumps(cf).encode()).hexdigest())


def arrays(*rows):
    return {k: [row.get(k, '') for row in rows] for k in (*FILING, 'items')}


class AutomaticExtractionTests(unittest.TestCase):
    def test_unseen_issuer_locators_and_values_generated_from_sources(self):
        result = validate_dataset(extracted())
        self.assertEqual(result['dataset_kind'], 'real_official_auto_verified')
        self.assertEqual({f['metric']: f['anchor'] for f in result['facts']},
                         {'revenue': 'portable-sale', 'assets': 'portable-asset'})
        self.assertEqual(read_model(result)['rows'][0]['current_display'], '6.15')
        self.assertEqual(result['narrative'], [])

    def test_mismatching_original_and_wrong_accession_hide_values(self):
        for cf, expected in [(companyfacts(wrong_amount=True), 'companyfacts_mismatch'),
                             (companyfacts(wrong_accession=True), 'missing_same_filing_companyfacts')]:
            result = extracted(cf=cf)
            self.assertEqual({f['metric'] for f in result['facts']}, {'assets'})
            self.assertEqual(result['metric_outcomes'][0]['status'], expected)

    def test_distinct_same_period_values_are_rejected_even_when_one_matches(self):
        conflict = ('<ix:nonFraction id="other" name="us-gaap:Revenues" contextRef="year" unitRef="usd" '
                    'scale="6" format="ixt:num-dot-decimal">999</ix:nonFraction>')
        result = extracted(financial_document(conflict))
        self.assertEqual(result['metric_outcomes'][0]['status'], 'conflicting_original_values')

    def test_document_subject_and_nonstandard_format_rejected(self):
        with self.assertRaisesRegex(EvidenceError, 'document_subject_or_form_mismatch'):
            extracted(financial_document(metadata_cik='0000002002'))
        raw = financial_document().replace(b'format="ixt:num-dot-decimal">615',
                                            b'format="ixt:unknown">615')
        self.assertEqual(extracted(raw)['metric_outcomes'][0]['status'], 'unsupported_original_number')

    def test_subprocess_accepts_exact_source_bytes_and_rejects_wrong_receipt(self):
        raw = json.dumps(companyfacts()).encode()
        data = parse_in_worker(ISSUER, FILING, financial_document(), raw, observed_at=STAMP,
                               companyfacts_sha256=sha256(raw).hexdigest())
        self.assertEqual(len(data['facts']), 2)
        with self.assertRaisesRegex(EvidenceError, 'companyfacts_receipt_mismatch'):
            parse_in_worker(ISSUER, FILING, financial_document(), raw, observed_at=STAMP,
                            companyfacts_sha256='0' * 64)

    def test_duplicate_anchor_does_not_become_a_linked_fact(self):
        duplicate = financial_document().replace(b'<table>', b'<div id="portable-sale"></div><table>')
        result = extracted(duplicate)
        self.assertEqual({f['metric'] for f in result['facts']}, {'assets'})


class DiscoveryTests(unittest.TestCase):
    def test_directory_ambiguity_and_unknown(self):
        catalog = directory(DIRECTORY)
        self.assertEqual(query_directory(catalog, 'zzqq')[0]['cik'], CIK)
        self.assertEqual(len(query_directory(catalog, 'Unknown Placeholder')), 2)
        self.assertEqual(query_directory(catalog, 'NONEXISTENT'), [])

    def test_archive_disagreement_does_not_poison_independent_event_window(self):
        page_name = 'CIK0000001001-submissions-001.json'
        page = {'name': page_name, 'filingFrom': '2025-07-01', 'filingTo': '2025-08-02', 'filingCount': 1}
        first = dict(FILING, accessionNumber='0000001001-25-000001', filingDate='2025-08-03',
                     reportDate='2025-06-30', form='10-Q')
        recent = [dict(FILING), dict(FILING, accessionNumber='0000001001-26-000003', form='8-K/A',
                                     filingDate='2026-11-15', reportDate='2026-11-12', items='2.02,9.01'),
                  dict(FILING, accessionNumber='0000001001-26-000004', form='6-K',
                       filingDate='2026-10-10', reportDate='2026-10-11'),
                  dict(FILING, accessionNumber='0000001001-25-000010', form='3', filingDate='2025-08-04',
                       reportDate='2025-08-04')]
        index = {'cik': CIK, 'filings': {'recent': arrays(*recent), 'files': [page]}}
        calls = []
        window = collect_window(index, CIK, '2026-11-27', '2025-07-01',
                                lambda name: calls.append(name) or arrays(first))
        self.assertEqual(calls, [page_name])
        self.assertFalse(window['complete'])
        self.assertEqual(window['rejected_pages'][0]['actual_to'], '2025-08-03')
        events = announcement_window(window, CIK)
        self.assertEqual((events['start'], events['state']), ('2026-08-30', 'observed'))
        self.assertTrue(events['entries'][0]['is_amendment'])
        self.assertEqual(events['entries'][0]['items'][0]['code'], '2.02')
        self.assertEqual(events['entries'][1]['form'], '6-K')

    def test_revision_remains_distinct_and_precedes_original(self):
        amended = dict(FILING, accessionNumber='0000001001-26-000005', form='10-K/A',
                       filingDate='2026-11-10')
        history, _ = periodic_filings({'rows': [FILING, amended]}, CIK)
        self.assertEqual(history[0]['accession'], amended['accessionNumber'])
        self.assertEqual(history[0]['base_accession'], ACC)

    def test_catalog_cached_and_expired_catalog_degrades_with_source_reason(self):
        class Client:
            status = 'ok'
            calls = 0
            def get(self, url, kind):
                self.calls += 1
                return SourceResult(self.status, json.dumps(DIRECTORY).encode() if self.status == 'ok' else b'',
                                    200 if self.status == 'ok' else 403, 'application/json')
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(Path(root) / 'test.sqlite')
            elapsed = [datetime.fromisoformat(STAMP)]
            client = Client()
            source = Source(cache, client, lambda: elapsed[0])
            source.fetch(DIRECTORY_URL, ttl=timedelta(days=1))
            self.assertEqual(source.fetch(DIRECTORY_URL, ttl=timedelta(days=1))[1]['cache'], 'fresh')
            self.assertEqual(client.calls, 1)
            elapsed[0] += timedelta(days=2)
            client.status = 'authorization_blocked'
            self.assertEqual(source.fetch(DIRECTORY_URL, stale=True)[1]['refresh_status'], 'authorization_blocked')
            with self.assertRaisesRegex(SourceUnavailable, 'authorization_blocked'):
                source.fetch(DIRECTORY_URL)

    def test_loopback_research_rejects_cross_origin_and_arbitrary_urls(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'data.sqlite')
            research = Research(Path(root) / 'sec.sqlite')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(store, research))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host = f'http://127.0.0.1:{server.server_port}'
                def post(origin, body):
                    con = HTTPConnection('127.0.0.1', server.server_port)
                    try:
                        con.request('POST', '/api/research', json.dumps(body),
                                    {'Origin': origin, 'Content-Type': 'application/json'})
                        response = con.getresponse()
                        response.read()
                        return response.status
                    finally:
                        con.close()
                self.assertEqual(post('https://external.invalid', {'cik': CIK}), 403)
                self.assertEqual(post(host, {'cik': CIK, 'url': 'https://external.invalid'}), 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                research.close()
