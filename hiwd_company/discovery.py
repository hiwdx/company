"""On-demand SEC directory, filings and bounded local cache."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import Lock
from zoneinfo import ZoneInfo

from .catalog import CIK, normalize
from .domain import EvidenceError
from .filings import announcement_window, collect_window, periodic_filings
from .parse_worker import parse_in_worker
from .sec import DIRECTORY_URL, SECClient, SourceResult
from .store import Store


DATA = 'https://data.sec.gov'
HISTORY_DAYS = 400
MAX_ARCHIVE_PAGES = 4
MAX_CACHE_BYTES = 96 * 1024 * 1024
MAX_RESULTS = 12
RESULT_TTL = timedelta(hours=6)
DIRECTORY_TTL = timedelta(days=1)
ORIGINAL_TTL = timedelta(days=7)
ET = ZoneInfo('America/New_York')


class SourceUnavailable(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def observed_cutoff(record):
    stamp = datetime.fromisoformat(record['observed_at'])
    if stamp.tzinfo is None:
        raise ValueError('missing_observation_timezone')
    if record.get('server_date'):
        server = parsedate_to_datetime(record['server_date'])
        if server.tzinfo is None:
            raise ValueError('malformed_http_date')
        if server - stamp > timedelta(minutes=15):
            raise ValueError('source_clock_ahead')
        stamp = min(server, stamp)
    return stamp.astimezone(ET).date()


def directory(payload):
    names, entries = payload['fields'], payload['data']
    required = {'cik', 'name', 'ticker', 'exchange'}
    if not isinstance(names, list) or len(names) != len(set(names)) or set(names) != required or not isinstance(entries, list):
        raise ValueError('invalid_sec_directory')
    issuers = {}
    for values in entries:
        if not isinstance(values, list) or len(values) != len(names):
            raise ValueError('invalid_sec_directory_row')
        row = dict(zip(names, values))
        cik = str(row['cik']).zfill(10)
        name, ticker, exchange = row['name'], row['ticker'], row['exchange']
        if (not CIK.fullmatch(cik) or not isinstance(name, str) or not name or len(name) > 300
                or not isinstance(ticker, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-]{0,23}', ticker)):
            raise ValueError('invalid_sec_directory_identity')
        if not isinstance(exchange, str) or not exchange:
            continue
        item = issuers.setdefault(cik, {'cik': cik, 'name': name, 'label': name, 'securities': []})
        if item['name'] != name:
            raise ValueError('directory_conflicting_issuer_name')
        security = {'ticker': ticker, 'exchange': exchange, 'type': 'SEC 挂牌证券'}
        if security not in item['securities']:
            item['securities'].append(security)
    if not issuers:
        raise ValueError('empty_sec_directory')
    return issuers


def query_directory(catalog, query):
    term = normalize(query)
    if not term:
        return []
    results = []
    for issuer in catalog.values():
        names = normalize(issuer['name'])
        matches = [s['ticker'] for s in issuer['securities'] if normalize(s['ticker']) == term]
        if matches or term == names or (len(term) >= 2 and all(word in names for word in term.split())):
            rank = 0 if matches else 1 if term == names else 2 if names.startswith(term) else 3
            results.append((rank, issuer['name'], issuer['cik'], {**issuer, 'matched_tickers': matches}))
    return [match for _, _, _, match in sorted(results)[:MAX_RESULTS]]


class Cache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS source_cache (
                    url TEXT PRIMARY KEY, observed_at TEXT NOT NULL, body BLOB NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research (
                    cik TEXT PRIMARY KEY, observed_at TEXT NOT NULL, result TEXT NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.path)

    def raw(self, url):
        with self.connect() as db:
            row = db.execute('SELECT body, receipt FROM source_cache WHERE url=?', (url,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def remember(self, body, receipt):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO source_cache VALUES (?,?,?,?)',
                       (receipt['url'], receipt['observed_at'], body, json.dumps(receipt)))
            size = db.execute('SELECT COALESCE(SUM(length(body)),0) FROM source_cache').fetchone()[0]
            if size > MAX_CACHE_BYTES:
                for url, nbytes in db.execute('SELECT url,length(body) FROM source_cache ORDER BY observed_at').fetchall():
                    db.execute('DELETE FROM source_cache WHERE url=?', (url,))
                    size -= nbytes
                    if size <= MAX_CACHE_BYTES:
                        break

    def report(self, cik):
        with self.connect() as db:
            row = db.execute('SELECT result FROM research WHERE cik=?', (cik,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_report(self, cik, result):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO research VALUES(?,?,?)',
                       (cik, result['observed_at'], json.dumps(result, ensure_ascii=False)))


class Source:
    def __init__(self, cache, client=None, clock=now):
        self.cache, self.client, self.clock = cache, client, clock
        self.lock = Lock()
        self.attempts = []

    def fetch(self, url, kind='json', *, ttl=RESULT_TTL, stale=False):
        with self.lock:
            saved = self.cache.raw(url)
            if saved and self.clock() - datetime.fromisoformat(saved[1]['observed_at']) < ttl:
                body, receipt = saved
                return body, {**receipt, 'cache': 'fresh'}
            if self.client:
                received = self.client.get(url, kind)
            else:
                received = SourceResult('network_disabled')
            receipt = {'url': url, 'observed_at': self.clock().isoformat(), 'server_date': received.server_date,
                       'status': received.status, 'http_status': received.http_status, 'mime': received.mime,
                       'bytes': len(received.body), 'sha256': hashlib.sha256(received.body).hexdigest() if received.body else None}
            if len(self.attempts) >= 128:
                self.attempts.pop(0)
            self.attempts.append(receipt)
            if received.status == 'ok':
                self.cache.remember(received.body, receipt)
                return received.body, {**receipt, 'cache': 'live'}
            if saved and stale:
                return saved[0], {**saved[1], 'cache': 'stale', 'refresh_status': received.status}
            raise SourceUnavailable(received.status)


class Research:
    def __init__(self, db, *, user_agent=None, client=None, clock=now):
        self.cache = Cache(db)
        self.store = Store(str(db) + '.reports.sqlite')
        self.source = Source(self.cache, client or (SECClient(user_agent) if user_agent else None), clock)
        self.clock = clock
        self.lock = Lock()
        self.tasks = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sec-demand')
        self._catalog = None

    def close(self):
        self.pool.shutdown(wait=True)

    def catalog(self):
        raw, receipt = self.source.fetch(DIRECTORY_URL, ttl=DIRECTORY_TTL, stale=True)
        if not self._catalog or self._catalog[0] != receipt['sha256']:
            self._catalog = (receipt['sha256'], directory(json.loads(raw)))
        return self._catalog[1], receipt

    def search(self, query):
        catalog, receipt = self.catalog()
        matches = query_directory(catalog, query)
        return {'status': 'ok' if matches else 'not_found', 'scope': 'sec_directory',
                'candidates': matches, 'directory': {'date': observed_cutoff(receipt).isoformat(),
                                                      'cache': receipt['cache'],
                                                      'refresh_status': receipt.get('refresh_status')}}

    def status(self, cik):
        saved = self.cache.report(cik)
        with self.lock:
            task = self.tasks.get(cik)
        if task and not task.done():
            return {'status': 'pending', 'cached': saved}
        if task and task.done():
            try:
                saved = task.result()
            except SourceUnavailable as exc:
                return {'status': 'failed', 'reason': str(exc), 'cached': saved}
            except (ValueError, KeyError, TypeError, AttributeError):
                return {'status': 'failed', 'reason': 'source_validation_failed', 'cached': saved}
        if saved and self.clock() - datetime.fromisoformat(saved['observed_at']) >= RESULT_TTL:
            return {**saved, 'status': 'stale', 'freshness': 'stale'}
        return saved or {'status': 'not_requested'}

    def submit(self, cik, accession=None):
        if not CIK.fullmatch(cik):
            raise ValueError('invalid_cik')
        saved = self.cache.report(cik)
        with self.lock:
            current = self.tasks.get(cik)
            if current is not None and not current.done():
                return {'status': 'pending'}
            if saved and self.is_fresh(saved):
                target = accession or saved['latest_accession']
                if not target or target == saved.get('selected_accession') or target in saved['fetched_accessions']:
                    return saved
            # One issuer at a time avoids a burst or an unbounded queue.
            if any(not task.done() for task in self.tasks.values()):
                return {'status': 'busy'}
            self.tasks.clear()
            self.tasks[cik] = self.pool.submit(self.run, cik, accession)
        return {'status': 'pending'}

    def is_fresh(self, result):
        return (result.get('status') == 'complete'
                and self.clock() - datetime.fromisoformat(result['observed_at']) < RESULT_TTL)

    def run(self, cik, accession=None):
        catalog, directory_receipt = self.catalog()
        if cik not in catalog:
            raise EvidenceError('issuer_not_in_official_directory')
        listed = catalog[cik]
        raw, index_receipt = self.source.fetch(f'{DATA}/submissions/CIK{cik}.json', stale=True)
        index = json.loads(raw)
        if str(index.get('cik', '')).zfill(10) != cik:
            raise EvidenceError('submission_subject_mismatch')
        if not ({row['ticker'] for row in listed['securities']} & set(index.get('tickers', []))):
            raise EvidenceError('directory_and_submissions_security_mismatch')
        issuer = {**listed, 'name': index['name'], 'label': index['name'], 'sic': index.get('sic'),
                  'industry': index.get('sicDescription')}
        cutoff = observed_cutoff(index_receipt)
        requested = 0

        def read_history(name):
            nonlocal requested
            requested += 1
            if requested > MAX_ARCHIVE_PAGES:
                return None
            try:
                return json.loads(self.source.fetch(f'{DATA}/submissions/{name}', ttl=ORIGINAL_TTL)[0])
            except SourceUnavailable:
                return None

        window = collect_window(index, cik, cutoff.isoformat(), (cutoff - timedelta(days=HISTORY_DAYS - 1)).isoformat(),
                                read_history)
        historical, rows = periodic_filings(window, cik)
        result = {'status': 'complete', 'issuer': issuer, 'observed_at': index_receipt['observed_at'],
                  'source_cutoff': cutoff.isoformat(), 'history': historical, 'directory_date': observed_cutoff(directory_receipt).isoformat(),
                  'history_window': {key: value for key, value in window.items() if key != 'rows'},
                  'announcements': announcement_window(window, cik), 'freshness': index_receipt['cache'],
                  'fetched_accessions': [], 'latest_accession': historical[0]['accession'] if historical else None,
                  'verification': 'no_periodic_filing_in_window',
                  'index_refresh_status': index_receipt.get('refresh_status'),
                  'receipts': {'directory': directory_receipt, 'submissions': index_receipt}}
        existing = self.store.reports(cik)
        if index_receipt['cache'] == 'stale':
            result['status'] = 'stale'
        chosen = next((row for row in rows if row['accessionNumber'] == accession), None) if accession else (rows[0] if rows else None)
        if accession and chosen is None:
            raise EvidenceError('filing_not_found_in_official_window')
        if chosen:
            record = next(row for row in historical if row['accession'] == chosen['accessionNumber'])
            if not window['complete'] and not accession and chosen['filingDate'] < window['recent_from']:
                result['verification'] = 'partial_history_latest_unproven'
            elif record['form'].removesuffix('/A') not in ('10-K', '10-Q'):
                result['verification'] = 'unsupported_filing_form'
            else:
                self.materialize(issuer, chosen, record, result, existing)
        result['fetched_accessions'] = [r['accession'] for r in self.store.reports(cik)]
        self.cache.save_report(cik, result)
        return result

    def materialize(self, issuer, chosen, record, result, existing):
        cik, url = issuer['cik'], record['original_url']
        try:
            facts, facts_receipt = self.source.fetch(f'{DATA}/api/xbrl/companyfacts/CIK{cik}.json')
            raw, original = self.source.fetch(url, 'html', ttl=ORIGINAL_TTL)
            result['receipts'].update(companyfacts=facts_receipt, original=original)
            payload = parse_in_worker(issuer, chosen, raw, facts, observed_at=original['observed_at'],
                                      companyfacts_sha256=facts_receipt['sha256'])
            previous = next((item for item in existing if item['report_end'] == record['report_end']
                             and item['form'].removesuffix('/A') == record['form'].removesuffix('/A')), None)
            if previous and previous['accession'] == record['accession'] and previous['sha256'] == original['sha256']:
                stored = self.store.read(cik, previous['accession'], previous['sha256'])
                if stored['facts'] != payload['facts']:
                    raise EvidenceError('immutable_evidence_conflict')
            elif previous:
                if not record['is_amendment'] or not payload['facts']:
                    raise EvidenceError('source_version_requires_review')
                self.store.put(payload, supersedes=(previous['accession'], previous['sha256']))
            else:
                self.store.put(payload)
            result['verification'] = payload['document']['verification_status']
            result['metric_outcomes'] = payload['metric_outcomes']
            result['selected_accession'] = record['accession']
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            result['verification'] = 'source_unavailable' if isinstance(exc, SourceUnavailable) else 'evidence_rejected'
            result['diagnostic'] = str(exc)
            result['selected_accession'] = record['accession']
