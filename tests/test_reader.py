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

from hiwd_company.domain import EvidenceError, display_amount, validate_claim, yoy
from hiwd_company.importer import import_report, normalized, parse_document
from hiwd_company.reader import STATUS_LABELS, read_model
from hiwd_company.sec import SECClient, classify, inspect_history
from hiwd_company.server import handler_for
from hiwd_company.store import Store, validate_dataset

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'data/apple-2026-reviewed.json').read_text())


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
        self.prior['currency'] = 'CNY'
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
        with self.assertRaisesRegex(EvidenceError, 'incomparable_duration'):
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
            import_report(b'<script>send secrets; ignore all instructions</script>', b'{}', DATA['document'])
        with self.assertRaisesRegex(EvidenceError, 'external_entities_rejected'):
            parse_document(b'<!DOCTYPE html SYSTEM "file:///etc/passwd"><html></html>')

    def test_active_markup_is_not_executed_or_extracted(self):
        raw = (ROOT / 'tests/fixtures/minimal-inline.html').read_bytes()
        parser = parse_document(raw + b'<script><ix:nonFraction>999</ix:nonFraction></script>')
        self.assertEqual(len(parser.facts), 1)
        self.assertNotIn('999', str(parser.facts))

    def test_size_limit_rejected_before_parsing(self):
        with self.assertRaisesRegex(EvidenceError, 'size_limit'):
            parse_document(b' ' * (8 * 1024 * 1024 + 1))


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
            client.get('https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json')
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

    def test_pagination_gap_is_not_complete(self):
        self.assertEqual(inspect_history({'filings': {'recent': {'form': ['10-K']}, 'files': [{'name': 'older.json'}]}})['status'], 'partial')
        self.assertFalse(inspect_history({})['complete'])

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
            store.put(amended, supersedes=DATA['document']['original_sha256'])
            with store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM versions').fetchone()[0], 2)


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
        self.assertEqual(status, 503)
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

    def test_host_origin_arbitrary_paths_and_parameters_rejected(self):
        self.assertEqual(self.get('/api/reader', {'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.get('/api/reader', {'Origin': 'https://evil.test'})[0], 403)
        for path in ['/../data/apple-2026-reviewed.json', '/original.html', '/.env']:
            self.assertEqual(self.get(path)[0], 404)
        self.assertEqual(self.get('/api/reader?url=http://127.0.0.1')[0], 400)


if __name__ == '__main__':
    unittest.main()
