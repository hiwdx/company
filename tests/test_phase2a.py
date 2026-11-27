"""Regressions for amendment isolation, report retries and statement semantics."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hiwd_company.discovery import Research, SourceUnavailable
from hiwd_company.domain import EvidenceError, comparable
from hiwd_company.market_navigation import market_issuers, navigation_url, search_market
from hiwd_company.semantics import row_meaning, statement_types
from hiwd_company.store import Store
from test_on_demand import ACC, CIK, ISSUER, STAMP, extracted, financial_document


def amend(data, *, partial=False):
    payload = deepcopy(data)
    doc = payload['document']
    revised = '0000001001-26-000003'
    url = doc['original_url'].replace(ACC.replace('-', ''), revised.replace('-', ''))
    doc.update(accession=revised, form='10-K/A', is_amendment=True, published_on='2026-11-12',
               original_sha256='c'*64, original_url=url)
    for fact in payload['facts']:
        fact.update(version=revised, source_url=url, original_sha256='c'*64)
    if partial:
        payload['facts'] = payload['facts'][:1]
    return payload


class Amendments(unittest.TestCase):
    def test_partial_amendment_is_never_visible_as_verified_head(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'reports.sqlite')
            full = extracted()
            store.put(full)
            patch = amend(full, partial=True)
            doc = patch['document']
            with self.assertRaisesRegex(EvidenceError, 'amendment_requires_review'):
                store.put(patch, supersedes=(ACC, full['document']['original_sha256']))
            staged = store.stage_revision(patch)
            self.assertEqual(staged['impact']['missing'], ['assets:current'])
            self.assertIsNone(store.read(CIK, doc['accession']))
            self.assertEqual(len(store.read(CIK)['facts']), 2)
            with self.assertRaisesRegex(EvidenceError, 'partial_amendment_cannot_replace_baseline'):
                store.publish_revision(CIK, doc['accession'], doc['original_sha256'],
                                       {'note': 'Synthetic review cannot promote an incomplete amendment.'})
            self.assertEqual(store.read(CIK)['document']['accession'], ACC)

    def test_complete_amendment_requires_exact_review_before_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'reports.sqlite'
            store = Store(path)
            original = extracted()
            store.put(original)
            revised = amend(original)
            doc = revised['document']
            staged = store.stage_revision(revised)
            review = {'baseline': [ACC, original['document']['original_sha256']],
                      'amendment_sha256': doc['original_sha256'], 'impact': staged['impact'],
                      'note': 'Synthetic statement scope and positions independently reviewed.'}
            with self.assertRaisesRegex(EvidenceError, 'amendment_review_outdated'):
                store.publish_revision(CIK, doc['accession'], doc['original_sha256'], {**review, 'impact': {}})
            self.assertEqual(store.publish_revision(CIK, doc['accession'], doc['original_sha256'], review), 'published')
            self.assertEqual(Store(path).read(CIK)['document']['accession'], doc['accession'])
            self.assertEqual(store.read(CIK, *review['baseline'])['document']['accession'], ACC)

    def test_old_automatic_partial_head_is_quarantined_on_upgrade(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'reports.sqlite'
            store = Store(path)
            previous = extracted()
            previous['schema_version'] = 3
            store.put(previous)
            changed = amend(previous, partial=True)
            # Simulate a Phase 1C SQLite head before installing this migration.
            with store.connect() as conn:
                store._put(conn, changed, (ACC, previous['document']['original_sha256']))
            migrated = Store(path)
            self.assertEqual(migrated.read(CIK)['document']['accession'], ACC)
            self.assertEqual(migrated.reports(CIK)[0]['status'], 'needs_semantic_review')
            self.assertIsNone(migrated.read(CIK, changed['document']['accession']))

    def test_same_original_semantic_attestation_keeps_base_identity(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'reports.sqlite')
            new = extracted()
            old = deepcopy(new)
            old['schema_version'] = 3
            for f in old['facts']:
                f.pop('semantic')
            store.put(old)
            self.assertEqual(store.attest(new), 'attested')
            self.assertEqual(store.read(CIK)['schema_version'], 4)
            self.assertEqual(store.read(CIK)['document']['original_sha256'], old['document']['original_sha256'])


class RetryCache(unittest.TestCase):
    def test_selected_fresh_failure_does_not_lock_out_explicit_retry(self):
        with tempfile.TemporaryDirectory() as root:
            clock = lambda: datetime.fromisoformat(STAMP)
            research = Research(Path(root) / 'research.sqlite', clock=clock)
            saved = {'status': 'complete', 'observed_at': STAMP, 'latest_accession': ACC,
                     'selected_accession': ACC, 'fetched_accessions': [ACC], 'directory_status': 'observed',
                     'report': {'requested_accession': ACC, 'checked_at': STAMP, 'status': 'retryable_failure'}}
            research.cache.save_report(CIK, saved)
            try:
                with patch.object(research, 'run', return_value={**saved, 'report': {
                    **saved['report'], 'status': 'verified'}}) as run:
                    self.assertEqual(research.submit(CIK)['status'], 'pending')
                    self.assertEqual(research.tasks[CIK].result(2)['report']['status'], 'verified')
                    run.assert_called_once_with(CIK, None)
                verified = research.status(CIK)
                research.cache.save_report(CIK, verified)
                with patch.object(research, 'run') as run:
                    self.assertEqual(research.submit(CIK)['report']['status'], 'verified')
                    run.assert_not_called()
            finally:
                research.close()

    def test_transport_failure_keeps_directory_and_last_verified_facts(self):
        with tempfile.TemporaryDirectory() as root:
            research = Research(Path(root) / 'cache.sqlite', clock=lambda: datetime.fromisoformat(STAMP))
            data = extracted()
            research.store.put(data)
            receipt = {'report': {'checked_at': STAMP}, 'receipts': {}, 'directory_status': 'observed'}
            record = {'original_url': data['document']['original_url'], 'accession': ACC, 'is_amendment': False}
            try:
                with patch.object(research.source, 'fetch', side_effect=SourceUnavailable('fetch_failed')):
                    research.materialize(ISSUER, {}, record, receipt, research.store.reports(CIK))
                self.assertEqual(receipt['directory_status'], 'observed')
                self.assertEqual(receipt['report']['status'], 'retryable_failure')
                self.assertEqual(len(research.store.read(CIK)['facts']), 2)
            finally:
                research.close()


class MetricSemantics(unittest.TestCase):
    def test_md_and_a_metric_without_primary_statement_structure_is_rejected(self):
        raw = financial_document().replace(b'Income tax expense', b'Recruiting costs').replace(b'Net income', b'Adjusted snapshot')
        result = extracted(raw)
        self.assertEqual({fact['metric'] for fact in result['facts']}, {'assets'})

    def test_tax_and_profit_scope_are_distinct(self):
        stmt = {'income_statement'}
        net = row_meaning('revenue', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'Total revenue', stmt)
        gross = row_meaning('revenue', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Total revenue', stmt)
        self.assertNotEqual(net[0], gross[0])
        self.assertIsNone(row_meaning('net_income', 'NetIncomeLoss', 'Consolidated Net Income', stmt))
        self.assertEqual(row_meaning('net_income', 'ProfitLoss', 'Consolidated Net Income', stmt)[0], 'profit_consolidated')
        self.assertEqual(row_meaning('net_income', 'NetIncomeLoss', 'Net Income Attributable to Shareowners', stmt)[0],
                         'profit_parent')

    def test_bank_deposits_with_banks_and_after_provision_are_excluded(self):
        self.assertIsNone(row_meaning('deposits', 'Deposits', 'Deposits with banks', {'balance_sheet'}))
        self.assertEqual(row_meaning('deposits', 'Deposits', 'Deposits (included $100 at fair value)',
                                     {'balance_sheet'})[0], 'deposits')
        self.assertIsNone(row_meaning('net_interest', 'InterestIncomeExpenseNet',
                                      'Net interest income after provision', {'income_statement'}))


class MarketNavigation(unittest.TestCase):
    def test_four_samples_keep_issuer_ids_separate_from_cik_and_security(self):
        catalog = market_issuers()
        for code in ('00700.HK', '09988.HK', '600519.SH', '601398.SH'):
            result = search_market(code, catalog)[0]
            self.assertEqual(result['matched_tickers'], [code])
            self.assertNotIn('cik', result)
            self.assertEqual(result['status'], 'authorization_blocked')
        self.assertEqual(search_market('01398.HK', catalog)[0]['issuer_id'],
                         search_market('601398.SH', catalog)[0]['issuer_id'])

    def test_exchange_links_are_approved_home_pages_only(self):
        for url in ('https://www.hkexnews.hk/', 'https://www.hkexnews.hk/announcements', 'https://www.sse.com.cn/?stock=600519',
                    'http://www.cninfo.com.cn/', 'https://outside.invalid/'):
            with self.assertRaisesRegex(ValueError, 'unapproved_market_navigation'):
                navigation_url(url)
