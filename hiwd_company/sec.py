"""Explicit, opt-in SEC read adapter. No polling, retries, or identity rotation."""
from dataclasses import dataclass
import json
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
    if expected == 'json' and mime.split(';')[0].strip() != 'application/json':
        return 'wrong_mime'
    if expected == 'html' and mime.split(';')[0].strip() not in ('text/html', 'application/xhtml+xml'):
        return 'wrong_mime'
    return 'ok'


def inspect_history(payload):
    """A recent-only response cannot prove multi-year/90-day completeness."""
    filings = payload.get('filings', {})
    if not isinstance(filings.get('recent', {}).get('form'), list):
        return {'status': 'parse_failed', 'complete': False}
    pending = filings.get('files', [])
    return {'status': 'partial' if pending else 'ok', 'complete': not bool(pending),
            'unfetched_history_files': len(pending)}


class SECClient:
    def __init__(self, user_agent, opener=None):
        if not user_agent or '\n' in user_agent or '\r' in user_agent or len(user_agent) > 300:
            raise ValueError('SEC_USER_AGENT must contain a truthful project and PO-authorized contact')
        if 'hiwd company' not in user_agent.lower() or not re.search(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@)]+', user_agent):
            raise ValueError('Use hiwd company and an authorized email; do not publish the value')
        self.user_agent, self.opener = user_agent, opener or build_opener(NoRedirect())
        self.denied_hosts, self.last_request = set(), 0

    def get(self, url, expected='json'):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('data.sec.gov', 'www.sec.gov')
                or parsed.username or parsed.port or parsed.query or parsed.fragment):
            raise ValueError('Only canonical SEC HTTPS destinations are accepted')
        if not (re.fullmatch(r'/submissions/CIK\d{10}\.json', parsed.path)
                or re.fullmatch(r'/api/xbrl/companyfacts/CIK\d{10}\.json', parsed.path)
                or re.fullmatch(r'/Archives/edgar/data/\d+/\d{18}/[A-Za-z0-9._-]+\.htm', parsed.path)):
            raise ValueError('Unapproved SEC endpoint')
        if parsed.hostname in self.denied_hosts:
            return SourceResult('authorization_blocked')
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = Request(url, headers={'User-Agent': self.user_agent, 'Accept': 'application/json' if expected == 'json' else 'text/html'})
        try:
            with self.opener.open(request, timeout=40) as response:
                status, mime = response.status, response.headers.get('Content-Type', '')
                state = classify(status, mime, expected)
                if state in ('authorization_blocked', 'rate_limited'):
                    self.denied_hosts.add(parsed.hostname)
                body = response.read(8 * 1024 * 1024 + 1) if state == 'ok' else b''
                if len(body) > 8 * 1024 * 1024:
                    return SourceResult('size_limit', http_status=status, mime=mime)
                if state == 'ok' and expected == 'json':
                    try:
                        json.loads(body)
                    except (ValueError, UnicodeError):
                        state = 'parse_failed'
                return SourceResult(state, body if state == 'ok' else b'', status, mime)
        except HTTPError as exc:
            state = classify(exc.code, exc.headers.get('Content-Type', ''), expected)
            if exc.code in (401, 403, 429):
                self.denied_hosts.add(parsed.hostname)
            return SourceResult(state, http_status=exc.code)
        except (URLError, socket.timeout, TimeoutError):
            return SourceResult('fetch_failed')
