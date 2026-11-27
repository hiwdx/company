"""Loopback-only shared reader. Browser clients cannot supply network URLs."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .catalog import CIK, issuers, search
from .discovery import SourceUnavailable
from .domain import ACCESSION, SHA, EvidenceError
from .reader import read_model


ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'/': ('app/index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app/app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('app/style.css', 'text/css; charset=utf-8'),
          '/manifest.webmanifest': ('app/manifest.webmanifest', 'application/manifest+json')}


def list_reports(store, research, cik):
    local = store.reports(cik)
    if not research:
        return local
    result = research.cache.report(cik)
    if not result:
        return local
    verified = {row['accession']: row for row in research.store.reports(cik)}
    baseline = {row['accession']: row for row in local}
    rows = []
    for item in result['history']:
        accession = item['accession']
        prepared = verified.get(accession) or baseline.get(accession) or {'status': 'discovered'}
        rows.append({'label': item['report_end'], **prepared, **item})
    seen = {item['accession'] for item in rows}
    return rows + [item for item in local if item['accession'] not in seen]


def handler_for(store, research=None):
    catalog = issuers()
    supported = {issuer['cik'] for issuer in catalog}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'hiwd-company-local'

        def log_message(self, *_args):
            pass

        def send_body(self, status, body, mime='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def trusted(self, *, post=False):
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            approved = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            return host in approved and ((not post and not origin) or origin == 'http://' + host)

        def do_GET(self):
            if not self.trusted():
                return self.respond(403, {'status': 'access_denied'})
            path = urlsplit(self.path)
            if path.path.startswith('/api/'):
                return self.api(path)
            if path.path not in ASSETS or (path.path != '/' and path.query):
                return self.respond(404, {'status': 'not_found'})
            file, mime = ASSETS[path.path]
            return self.send_body(200, (ROOT / file).read_bytes(), mime)

        def do_POST(self):
            if not self.trusted(post=True):
                return self.respond(403, {'status': 'access_denied'})
            if self.path != '/api/research' or research is None:
                return self.respond(404, {'status': 'not_found'})
            if self.headers.get_content_type() != 'application/json':
                return self.respond(415, {'status': 'invalid_request'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 <= size <= 512:
                    raise ValueError('invalid_request_size')
                self.connection.settimeout(5)
                query = json.loads(self.rfile.read(size))
                if not isinstance(query, dict) or set(query) - {'cik', 'accession'}:
                    raise ValueError('invalid_query')
                cik, accession = query.get('cik'), query.get('accession')
                if not isinstance(cik, str) or not CIK.fullmatch(cik):
                    raise ValueError('invalid_cik')
                if accession is not None and (not isinstance(accession, str) or not ACCESSION.fullmatch(accession)):
                    raise ValueError('invalid_accession')
            except (ValueError, TypeError, TimeoutError, OSError):
                return self.respond(400, {'status': 'invalid_query'})
            task = research.submit(cik, accession)
            return self.respond(202 if task['status'] in ('pending', 'busy') else 200, task)

        def respond(self, status, payload):
            return self.send_body(status, json.dumps(payload, ensure_ascii=False).encode())

        def search_issuers(self, query):
            local = search(query, catalog)
            if research is None or not query.strip():
                return {'status': 'ok' if local else 'unsupported', 'scope': 'reviewed_sample_catalog', 'candidates': local}
            try:
                official = research.search(query)
                seen = {row['cik'] for row in official['candidates']}
                official['candidates'] += [row for row in local if row['cik'] not in seen]
                if official['candidates']:
                    official['status'] = 'ok'
                return official
            except (SourceUnavailable, ValueError, KeyError, TypeError, AttributeError) as exc:
                return {'status': 'ok' if local else 'source_unavailable', 'scope': 'reviewed_sample_catalog',
                        'reason': str(exc), 'candidates': local}

        def api(self, path):
            if len(path.query) > 1200:
                return self.respond(400, {'status': 'invalid_query'})
            query = parse_qs(path.query, keep_blank_values=True)
            if any(len(value) != 1 for value in query.values()):
                return self.respond(400, {'status': 'invalid_query'})
            params = {key: values[0] for key, values in query.items()}
            if path.path == '/api/search':
                if set(params) - {'q'} or len(params.get('q', '')) > 100:
                    return self.respond(400, {'status': 'invalid_query'})
                return self.respond(200, self.search_issuers(params.get('q', '')))
            if path.path not in ('/api/reports', '/api/reader', '/api/research'):
                return self.respond(404, {'status': 'not_found'})
            allowed = {'cik', 'accession', 'version', 'unit'} if path.path == '/api/reader' else {'cik'}
            if set(params) - allowed:
                return self.respond(400, {'status': 'invalid_query'})
            cik = params.get('cik')
            if (cik is None and path.path != '/api/reader') or (cik is not None and not CIK.fullmatch(cik)):
                return self.respond(400, {'status': 'invalid_query'})
            if path.path == '/api/research':
                return self.respond(200, research.status(cik) if research else {'status': 'not_requested'})
            if path.path == '/api/reports':
                return self.respond(200, {'reports': list_reports(store, research, cik)})
            accession, version = params.get('accession'), params.get('version')
            unit = params.get('unit', 'hundred_millions')
            if ((accession and (not cik or not ACCESSION.fullmatch(accession)))
                    or (version and (not accession or not SHA.fullmatch(version)))
                    or unit not in ('millions', 'hundred_millions')):
                return self.respond(400, {'status': 'invalid_query'})
            try:
                data = research.store.read(cik, accession, version) if research and cik else None
                if data is None:
                    data = store.read(cik, accession, version)
                if data is None:
                    if research and cik and research.cache.report(cik):
                        return self.respond(409, {'status': 'report_not_verified'})
                    return self.respond(404, {'status': 'unsupported' if cik and cik not in supported else 'not_found'})
                divisor = '1000000' if unit == 'millions' else '100000000'
                return self.respond(200, read_model(data, divisor))
            except (EvidenceError, ValueError, KeyError):
                return self.respond(503, {'status': 'evidence_validation_failed'})

    return Handler


def serve(store, port=8765, research=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler_for(store, research))
    print('hiwd company local reader: http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
