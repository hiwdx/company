"""Explicit SEC read adapter with bounded requests and validated disclosure windows."""
from dataclasses import dataclass
from datetime import date
import json
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_BODY = 24 * 1024 * 1024
ACCESSION = re.compile(r'\d{10}-\d{2}-\d{6}')
PRIMARY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\.html?')
HISTORY_FILE = re.compile(r'CIK(?P<cik>\d{10})-submissions-\d+\.json')
COLUMNS = ('accessionNumber', 'filingDate', 'reportDate', 'form', 'primaryDocument')


@dataclass
class SourceResult:
    status: str
    body: bytes = b''
    http_status: int = 0
    mime: str = ''


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def classify(status, mime, expected='json'):
    if status in (401, 403):
        return 'authorization_blocked'
    if status == 429:
        return 'rate_limited'
    if status != 200:
        return 'fetch_failed'
    media_type = mime.split(';')[0].strip().lower()
    allowed = ('application/json',) if expected == 'json' else ('text/html', 'application/xhtml+xml')
    return 'ok' if media_type in allowed else 'wrong_mime'


def parse_rows(page):
    if not isinstance(page, dict) or any(not isinstance(page.get(key), list) for key in COLUMNS):
        raise ValueError('missing_filing_column')
    size = len(page['form'])
    if any(not isinstance(values, list) or len(values) != size for values in page.values()):
        raise ValueError('unequal_filing_columns')
    records, seen = [], set()
    for values in zip(*(page[key] for key in COLUMNS)):
        if any(not isinstance(value, str) for value in values):
            raise ValueError('invalid_filing_column')
        accession, filed, end, form, primary = values
        filed_date = date.fromisoformat(filed)
        end_date = date.fromisoformat(end) if end else None
        if not ACCESSION.fullmatch(accession) or accession in seen or not form:
            raise ValueError('invalid_or_duplicate_accession')
        if form in ('10-K', '10-Q', '20-F', '6-K', '10-K/A', '10-Q/A', '20-F/A', '6-K/A'):
            # A foreign event may be dated the next day in the issuer's local time.
            max_lead = 1 if form.startswith('6-K') else 0
            if not PRIMARY.fullmatch(primary) or not end_date or (end_date - filed_date).days > max_lead:
                raise ValueError('malformed_report_record')
        seen.add(accession)
        records.append(dict(zip(COLUMNS, values)))
    return records


def inspect_history(payload, *, cik=None, start=None, end=None, forms=('10-K', '10-Q'), pages=None):
    """Validate the source arrays and prove the requested filing-date window."""
    pages = pages or {}
    try:
        filings = payload['filings']
        source_cik = str(payload['cik']).zfill(10)
        if not re.fullmatch(r'\d{10}', source_cik) or (cik and cik != source_cik):
            raise ValueError('history_issuer_mismatch')
        rows = parse_rows(filings['recent'])
        descriptors = filings['files']
        if not isinstance(descriptors, list):
            raise ValueError('missing_history_manifest')
        if start is None or end is None or not forms:
            return {'status': 'partial', 'complete': False, 'reason': 'window_unspecified'}
        since, until = map(date.fromisoformat, (start, end))
        if since > until:
            raise ValueError('invalid_history_window')
        pending, intervals, names = [], [], set()
        for item in descriptors:
            match = HISTORY_FILE.fullmatch(item['name'])
            first, last = map(date.fromisoformat, (item['filingFrom'], item['filingTo']))
            if not match or match['cik'] != source_cik or first > last or item['name'] in names:
                raise ValueError('invalid_history_manifest')
            names.add(item['name'])
            if first <= until and last >= since:
                if item['name'] not in pages:
                    pending.append(item['name'])
                    continue
                page = parse_rows(pages[item['name']])
                if (len(page) != item['filingCount'] or not page
                        or min(row['filingDate'] for row in page) != item['filingFrom']
                        or max(row['filingDate'] for row in page) != item['filingTo']):
                    raise ValueError('history_page_mismatch')
                rows.extend(page)
                intervals.append(item)
        if len({row['accessionNumber'] for row in rows}) != len(rows):
            raise ValueError('overlapping_history_records')
        # Only a stored observation date can cover the quiet days after the latest filing.
        recent_from = min((row['filingDate'] for row in parse_rows(filings['recent'])), default=None)
        covered_from = min([item['filingFrom'] for item in intervals] + ([recent_from] if recent_from else []), default=None)
        observed = payload.get('observed_on')
        observation = date.fromisoformat(observed) if observed else None
        complete = bool(not pending and recent_from and covered_from <= start and observation and until <= observation)
        matches = sorted((row for row in rows if start <= row['filingDate'] <= end and row['form'] in forms),
                         key=lambda row: (row['reportDate'], row['filingDate']), reverse=True)
        return {'status': 'ok' if complete else 'partial', 'complete': complete, 'window': [start, end],
                'forms': list(forms), 'recent_from': recent_from, 'observed_on': observed,
                'pending_pages': pending, 'page_manifest': descriptors, 'reviewed_pages': [item['name'] for item in intervals],
                'matching_filings': matches, 'indexed_rows': len(rows)}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {'status': 'parse_failed', 'complete': False}


class SECClient:
    def __init__(self, user_agent, opener=None):
        if not user_agent or '\n' in user_agent or '\r' in user_agent or len(user_agent) > 300:
            raise ValueError('SEC_USER_AGENT must contain a truthful project and PO-authorized contact')
        if 'hiwd company' not in user_agent.lower() or not re.search(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@)]+', user_agent):
            raise ValueError('Use hiwd company and an authorized contact')
        self.user_agent = user_agent
        self.opener = opener or build_opener(NoRedirect())
        self.stopped = None
        self.last_request = None

    def get(self, url, expected='json'):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc not in ('data.sec.gov', 'www.sec.gov')
                or parsed.query or parsed.fragment or expected not in ('json', 'html')):
            raise ValueError('Only canonical SEC HTTPS destinations are accepted')
        archive = re.fullmatch(r'/Archives/edgar/data/[1-9]\d{0,9}/\d{18}/[A-Za-z0-9][A-Za-z0-9._-]*\.html?', parsed.path)
        data = re.fullmatch(r'/submissions/CIK\d{10}(?:-submissions-\d+)?\.json|/api/xbrl/companyfacts/CIK\d{10}\.json', parsed.path)
        if not ((parsed.netloc == 'www.sec.gov' and expected == 'html' and archive)
                or (parsed.netloc == 'data.sec.gov' and expected == 'json' and data)):
            raise ValueError('Unapproved SEC endpoint')
        if self.stopped:
            return SourceResult(self.stopped)
        if self.last_request is not None:
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = Request(url, headers={'User-Agent': self.user_agent,
                          'Accept': 'application/json' if expected == 'json' else 'text/html'})
        try:
            with self.opener.open(request, timeout=35) as response:
                status, mime = response.status, response.headers.get('Content-Type', '')
                state = self.record_status(status, mime, expected)
                body = response.read(MAX_BODY + 1) if state == 'ok' else b''
                if len(body) > MAX_BODY:
                    return SourceResult('size_limit', http_status=status, mime=mime)
                if state == 'ok':
                    try:
                        if expected == 'json' and not isinstance(json.loads(body), dict):
                            state = 'parse_failed'
                        if expected == 'html':
                            lower = body.lower()
                            is_filing = b'ix:nonfraction' in lower or b'ix:nonnumeric' in lower
                            if not is_filing and b'<title>' in lower and any(
                                phrase in lower for phrase in (b'access denied', b'undeclared automated tool', b'request rate threshold', b'page not found')
                            ):
                                state = 'error_document'
                    except (ValueError, UnicodeError):
                        state = 'parse_failed'
                return SourceResult(state, body if state == 'ok' else b'', status, mime)
        except HTTPError as exc:
            mime = exc.headers.get('Content-Type', '')
            return SourceResult(self.record_status(exc.code, mime, expected), http_status=exc.code, mime=mime)
        except (URLError, socket.timeout, TimeoutError):
            return SourceResult('fetch_failed')

    def record_status(self, status, mime, expected):
        state = classify(status, mime, expected)
        if state in ('authorization_blocked', 'rate_limited'):
            self.stopped = state
        return state
