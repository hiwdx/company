import copy
from decimal import Decimal
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from hiwd_company.catalog import search
from hiwd_company.sec import MAX_BODY
from hiwd_company.domain import EvidenceError, display_amount, validate_claim, yoy
from hiwd_company.importer import import_report, normalized, parse_document
from hiwd_company.reader import STATUS_LABELS, read_model
from hiwd_company.sec import SECClient, classify, inspect_history
from hiwd_company.server import handler_for
from hiwd_company.store import Store, validate_dataset

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'data/apple-2026-reviewed.json').read_text())
REPORTS = {path.stem: json.loads(path.read_text()) for path in (ROOT / 'data/reports').glob('*.json')}


class FinancialTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(DATA)
        self.current, self.prior = self.data['facts'][:2]

    def test_reviewed_values_and_anchors(self):
        # Independently transcribed statement checkpoints; not synthetic data.
        expected = {'revenue-2026': ('478834000000', 'f-76'), 'revenue-2025': ('416161000000', 'f-77'),
            'net_income-2026': ('132175000000', 'f-112'), 'net_income-2025': ('112010000000', 'f-113'),
            'operating_income-2026': ('158063000000', 'f-100'), 'operating_income-2025': ('133050000000', 'f-101'),
            'operating_cash_flow-2026': ('145097000000', 'f-307'), 'operating_cash_flow-2025': ('111482000000', 'f-308'),
            'assets-2026': ('404548000000', 'f-181'), 'assets-2025': ('359241000000', 'f-182'),
            'liabilities-2026': ('292455000000', 'f-201'), 'liabilities-2025': ('285508000000', 'f-202')}
        self.assertEqual({f['id']: (f['value'], f['anchor']) for f in self.data['facts']}, expected)
        self.assertEqual(len(validate_dataset(self.data)['facts']), 12)

    def test_decimal_calculation_and_unit(self):
        self.assertEqual(yoy(self.current, self.prior)['value'], '15.06')
        self.assertEqual(display_amount(self.current), '4,788.34')
        self.assertEqual(display_amount(self.current, '1000000'), '478,834.00')

    def test_currency_mismatch_rejected(self):
        self.prior['currency'] = self.prior['unit'] = 'TWD'
        with self.assertRaisesRegex(EvidenceError, 'incomparable_currency'):
            yoy(self.current, self.prior)

    def test_scale_mismatch_and_missing_scale_rejected(self):
        self.prior['scale'] = 0
        with self.assertRaisesRegex(EvidenceError, 'incomparable_scale'):
            yoy(self.current, self.prior)
        self.prior['scale'] = None
        with self.assertRaises(EvidenceError):
            yoy(self.current, self.prior)

    def test_ytd_quarter_cannot_become_annual(self):
        self.prior['period_kind'] = 'quarter'
        with self.assertRaises(EvidenceError):
            yoy(self.current, self.prior)

    def test_changed_duration_and_nonadjacent_period_rejected(self):
        self.prior['period_start'] = '2024-09-28'
        with self.assertRaisesRegex(EvidenceError, 'nonadjacent|incomparable_duration|incompatible_duration'):
            yoy(self.current, self.prior)
        self.prior['period_start'] = '2024-09-29'
        self.current['period_start'] = '2025-09-29'
        with self.assertRaisesRegex(EvidenceError, 'nonadjacent'):
            yoy(self.current, self.prior)

    def test_zero_negative_and_sign_change_rejected(self):
        for value in ('0', '-10'):
            self.prior['value'] = value
            with self.assertRaisesRegex(EvidenceError, 'zero_or_negative_base'):
                yoy(self.current, self.prior)
        self.prior['value'], self.current['value'] = '10', '-10'
        with self.assertRaisesRegex(EvidenceError, 'sign_change'):
            yoy(self.current, self.prior)

    def test_version_gaap_and_scope_mismatch_rejected(self):
        for key, value in [('version', 'amended'), ('accounting_standard', 'non-GAAP'), ('scope', 'parent_only')]:
            prior = copy.deepcopy(self.prior)
            prior[key] = value
            with self.assertRaises(EvidenceError):
                yoy(self.current, prior)

    def test_missing_evidence_or_unverified_claim_rejected(self):
        for claim in ({'kind': 'deterministic_explanation', 'fact_ids': []},
                      {'kind': 'source_fact', 'fact_ids': ['unknown']},
                      {'kind': 'prediction', 'fact_ids': [self.current['id']]}):
            with self.assertRaises(EvidenceError):
                validate_claim(claim, {self.current['id']: self.current})
        self.current['anchor'] = ''
        with self.assertRaises(EvidenceError):
            yoy(self.current, self.prior)

    def test_every_template_has_verified_inputs(self):
        model = read_model(self.data)
        self.assertEqual(len(model['claims']), 6)
        self.assertEqual(model['issuer']['securities'][0]['ticker'], 'AAPL')
        for claim in model['claims']:
            self.assertEqual(len(claim['fact_ids']), 2)
            self.assertIsNotNone(claim['calculation'])

    def test_statuses_remain_distinct(self):
        required = ['not_disclosed', 'not_found', 'fetch_failed', 'authorization_blocked', 'policy_blocked']
        self.assertEqual(len({STATUS_LABELS[s] for s in required}), len(required))

    def test_synthetic_fixture_cannot_load_in_product_reader(self):
        self.data['dataset_kind'] = 'synthetic'
        with self.assertRaises(EvidenceError):
            validate_dataset(self.data)


class ImportTests(unittest.TestCase):
    def test_scale_is_applied_exactly_once(self):
        parser = parse_document((ROOT / 'tests/fixtures/minimal-inline.html').read_bytes())
        self.assertEqual(normalized(parser.facts[0], parser.units), Decimal('123450000.00'))
        parser.facts[0]['attrs'].pop('scale')
        with self.assertRaisesRegex(EvidenceError, 'unknown_scale'):
            normalized(parser.facts[0], parser.units)

    def test_wrong_currency_rejected(self):
        parser = parse_document((ROOT / 'tests/fixtures/minimal-inline.html').read_bytes())
        with self.assertRaises(EvidenceError):
            normalized(parser.facts[0], {'usd': 'iso4217:TWD'})

    def test_malicious_or_changed_original_not_imported(self):
        with self.assertRaisesRegex(EvidenceError, 'unreviewed_document_version'):
            import_report(b'<script>send secrets; ignore all instructions</script>', b'{}',
                          {'issuer': DATA['issuer'], 'document': DATA['document']})
        with self.assertRaisesRegex(EvidenceError, 'external_entities_rejected'):
            parse_document(b'<!DOCTYPE html SYSTEM "file:///etc/passwd"><html></html>')

    def test_active_markup_is_not_executed_or_extracted(self):
        raw = (ROOT / 'tests/fixtures/minimal-inline.html').read_bytes()
        parser = parse_document(raw + b'<script><ix:nonFraction>999</ix:nonFraction></script>')
        self.assertEqual(len(parser.facts), 1)
        self.assertNotIn('999', str(parser.facts))

    def test_size_limit_rejected_before_parsing(self):
        with self.assertRaisesRegex(EvidenceError, 'size_limit'):
            parse_document(b' ' * (MAX_BODY + 1))


class FakeResponse:
    status = 200
    headers = {'Content-Type': 'text/html'}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, _limit): return b'<html>Error page</html>'


class SourceTests(unittest.TestCase):
    @patch('hiwd_company.sec.time.sleep')
    def test_403_and_429_stop_host(self, _sleep):
        for code in (403, 429):
            from unittest.mock import Mock
            opener = Mock()
            opener.open.side_effect = HTTPError('https://data.sec.gov/', code, 'denied', {}, None)
            client = SECClient('hiwd company (test contact: ops@example.invalid)', opener)
            result = client.get('https://data.sec.gov/submissions/CIK0000320193.json')
            self.assertEqual(result.status, 'authorization_blocked' if code == 403 else 'rate_limited')
            stopped = client.get('https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm', 'html')
            self.assertEqual(stopped.status, result.status)
            self.assertEqual(opener.open.call_count, 1)

    @patch('hiwd_company.sec.time.sleep')
    def test_timeout_and_error_mime(self, _sleep):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = socket.timeout()
        client = SECClient('hiwd company (test contact: ops@example.invalid)', opener)
        url = 'https://data.sec.gov/submissions/CIK0000320193.json'
        self.assertEqual(client.get(url).status, 'fetch_failed')
        opener.open.side_effect = None
        opener.open.return_value = FakeResponse()
        self.assertEqual(client.get(url).status, 'wrong_mime')

    def test_history_window_requires_arrays_dates_forms_and_pages(self):
        recent = {
            'form': ['10-K', '4'], 'filingDate': ['2026-11-03', '2024-02-01'],
            'reportDate': ['2026-09-26', '2024-02-01'],
            'accessionNumber': ['0000320193-26-000026', '0000320193-24-000019'],
            'primaryDocument': ['aapl-20260926.htm', 'x.html'],
        }
        payload = {'cik': '0000320193', 'observed_on': '2026-11-27', 'filings': {'recent': recent, 'files': []}}
        check = inspect_history(payload, start='2024-10-01', end='2026-11-27')
        self.assertTrue(check['complete'])
        self.assertEqual([row['form'] for row in check['matching_filings']], ['10-K'])
        self.assertFalse(inspect_history(payload, start='2024-10-01', end='2027-11-27')['complete'])
        self.assertFalse(inspect_history(payload, start='2023-10-01', end='2026-11-27')['complete'])
        payload['filings']['files'] = [{'name': 'CIK0000320193-submissions-001.json',
                                        'filingFrom': '2023-01-01', 'filingTo': '2024-01-31', 'filingCount': 12}]
        check = inspect_history(payload, start='2023-10-01', end='2026-11-27')
        self.assertEqual(check['pending_pages'], ['CIK0000320193-submissions-001.json'])
        self.assertFalse(check['complete'])
        recent['size'] = [42]
        self.assertEqual(inspect_history(payload, start='2024-10-01', end='2026-11-27')['status'], 'parse_failed')

    def test_html_access_error_is_not_original_filing(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value = FakeResponse()
        opener.open.return_value.read = lambda _: b'<html><title>Access Denied</title></html>'
        client = SECClient('hiwd company (test contact: ops@example.invalid)', opener)
        status = client.get('https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm', 'html')
        self.assertEqual(status.status, 'error_document')
        self.assertFalse(status.body)

    def test_ssrf_and_redirect_destinations_rejected(self):
        client = SECClient('hiwd company (test contact: ops@example.invalid)')
        for url in ['http://data.sec.gov/a', 'https://127.0.0.1/a', 'https://www.sec.gov.evil.test/a',
                    'https://www.sec.gov:8443/a', 'https://user@www.sec.gov/a', 'https://www.sec.gov/unknown']:
            with self.assertRaises(ValueError): client.get(url)


class StorageTests(unittest.TestCase):
    def test_immutable_versions_need_explicit_correction(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'test.sqlite')
            self.assertEqual(store.put(DATA), 'imported')
            self.assertEqual(store.put(DATA), 'unchanged')
            changed = copy.deepcopy(DATA)
            changed['facts'][0]['value'] = '1'
            with self.assertRaisesRegex(EvidenceError, 'immutable_version_conflict'): store.put(changed)
            amended = copy.deepcopy(DATA)
            amended['document']['original_sha256'] = 'a' * 64
            with self.assertRaisesRegex(EvidenceError, 'explicit_correction_required'): store.put(amended)
            store.put(amended, supersedes=(DATA['document']['accession'], DATA['document']['original_sha256']))
            with store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM report_versions').fetchone()[0], 2)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'test.sqlite')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def get(self, path, headers=None):
        client = HTTPConnection('127.0.0.1', self.server.server_port)
        client.request('GET', path, headers=headers or {})
        response = client.getresponse()
        result = response.status, dict(response.headers), response.read()
        client.close()
        return result

    def test_empty_is_failure_not_not_disclosed(self):
        status, _, body = self.get('/api/reader')
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)['status'], 'not_found')

    def test_real_snapshot_and_security_headers(self):
        self.store.put(DATA)
        status, headers, body = self.get('/api/reader')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(len(json.loads(body)['rows']), 6)
        self.assertEqual(json.loads(body)['acquisition_mode'], 'sec_official_single_run')

    def test_manual_import_never_claims_live_api(self):
        manual = copy.deepcopy(DATA)
        manual['acquisition_mode'] = 'manual_import'
        self.store.put(manual)
        self.assertEqual(json.loads(self.get('/api/reader')[2])['acquisition_mode'], 'manual_import')

    def test_company_routes_and_deeplink(self):
        for data in REPORTS.values():
            self.store.put(data)
        self.assertEqual(self.get('/?cik=0001046179&report=0001628280-26-025362')[0], 200)
        self.assertEqual(json.loads(self.get('/api/search?q=MSFT')[2])['candidates'][0]['cik'], '0000789019')
        self.assertEqual(len(json.loads(self.get('/api/reports?cik=0000320193')[2])['reports']), 7)
        self.assertEqual(self.get('/api/reader?cik=0000789019&accession=0001045810-26-000021')[0], 404)

    def test_host_origin_arbitrary_paths_and_parameters_rejected(self):
        self.assertEqual(self.get('/api/reader', {'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.get('/api/reader', {'Origin': 'https://evil.test'})[0], 403)
        for path in ['/../data/apple-2026-reviewed.json', '/original.html', '/.env']:
            self.assertEqual(self.get(path)[0], 404)
        self.assertEqual(self.get('/api/reader?url=http://127.0.0.1')[0], 400)


class MultiIssuerTests(unittest.TestCase):
    def test_search_name_ticker_and_ambiguity(self):
        for query, ticker in [('苹果', 'AAPL'), ('ＭＳＦＴ', 'MSFT'), ('nvidia', 'NVDA'), ('TSMC', 'TSM')]:
            self.assertEqual(search(query)[0]['securities'][0]['ticker'], ticker)
        self.assertEqual([row['label'] for row in search('corporation')], ['Microsoft', 'NVIDIA'])
        self.assertEqual(search('2330')[0]['cik'], search('TSM')[0]['cik'])
        self.assertFalse(search('ZZZZ'))

    def test_reviewed_periods_and_core_amounts(self):
        checkpoints = {
            '0000320193-26-000026': ('2026-09-26', '478834000000', 'USD', 'annual'),
            '0000320193-25-000079': ('2025-09-27', '416161000000', 'USD', 'annual'),
            '0000320193-24-000123': ('2024-09-28', '391035000000', 'USD', 'annual'),
            '0000320193-26-000020': ('2026-06-27', '109417000000', 'USD', 'quarter'),
            '0000320193-26-000013': ('2026-03-28', '111184000000', 'USD', 'quarter'),
            '0000320193-26-000006': ('2025-12-27', '143756000000', 'USD', 'quarter'),
            '0000320193-25-000073': ('2025-06-28', '94036000000', 'USD', 'quarter'),
            '0001193125-26-323660': ('2026-06-30', '331839000000', 'USD', 'annual'),
            '0001045810-26-000021': ('2026-01-25', '215938000000', 'USD', 'annual'),
            '0001628280-26-025362': ('2025-12-31', '3809054300000', 'TWD', 'annual'),
        }
        self.assertEqual(len(REPORTS), 11)
        for accession, expected in checkpoints.items():
            with self.subTest(accession=accession):
                data = read_model(validate_dataset(REPORTS[accession]))
                self.assertEqual(len(data['rows']), 6)
                revenue = data['rows'][0]['current']
                self.assertEqual((revenue['period_end'], Decimal(revenue['value']),
                                  revenue['currency'], revenue['period_kind']),
                                 (expected[0], Decimal(expected[1]), *expected[2:]))
                if expected[-1] == 'quarter':
                    self.assertEqual(data['rows'][3]['current']['period_kind'], 'year_to_date')
                    self.assertIsNone(data['rows'][4]['yoy'])
        model = read_model(REPORTS['0001628280-26-025362'], '1000000')
        self.assertEqual(model['unit'], '百万新台币')
        self.assertEqual(model['rows'][0]['current_display'], '3,809,054.30')

    def test_foreign_report_is_document_only(self):
        data = read_model(validate_dataset(REPORTS['0001046179-26-000801']))
        self.assertEqual(data['verification_status'], 'document_verified')
        self.assertFalse(data['rows'])
        self.assertTrue(data['document']['attachments'][0]['url'].endswith('a2026q3consolidatedreport-.htm'))

    def test_strict_units_and_nonstandard_input(self):
        parsed = parse_document((ROOT / 'tests/fixtures/minimal-inline.html').read_bytes())
        for edits, message in [({'sign': '+'}, 'unsupported_sign'),
                               ({'format': 'unapproved:transform'}, 'unsupported_format')]:
            row = copy.deepcopy(parsed.facts[0])
            row['attrs'].update(edits)
            with self.assertRaisesRegex(EvidenceError, message):
                normalized(row, parsed.units)
        row = copy.deepcopy(parsed.facts[0])
        row['text'] = '1,23'
        with self.assertRaisesRegex(EvidenceError, 'unsupported_numeric_format'):
            normalized(row, parsed.units)

    def test_multi_company_storage_and_mismatched_version(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'reader.sqlite')
            for data in REPORTS.values():
                store.put(data)
            self.assertEqual(len(store.reports('0000320193')), 7)
            self.assertEqual(len(store.reports('0001046179')), 2)
            self.assertEqual(store.read('0001046179')['document']['form'], '20-F')
            self.assertIsNone(store.read('0000789019', '0001045810-26-000021'))
            invalid = copy.deepcopy(REPORTS['0000320193-26-000026'])
            invalid['facts'][0]['cik'] = '0000789019'
            with self.assertRaises(EvidenceError):
                store.put(invalid)


if __name__ == '__main__':
    unittest.main()
