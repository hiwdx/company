"""Loopback-only prototype. No upload, URL fetch, or original-markup routes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .catalog import CIK, issuers, search
from .domain import ACCESSION, SHA, EvidenceError
from .reader import read_model

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'/': ('app/index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app/app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('app/style.css', 'text/css; charset=utf-8'),
          '/manifest.webmanifest': ('app/manifest.webmanifest', 'application/manifest+json')}


def handler_for(store):
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

        def do_GET(self):
            host = self.headers.get('Host', '')
            approved = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            origin = self.headers.get('Origin')
            if host not in approved or (origin and origin not in {'http://' + h for h in approved}):
                return self.send_body(403, b'{"status":"access_denied"}')
            path = urlsplit(self.path)
            if path.path.startswith('/api/'):
                return self.api(path)
            if path.path not in ASSETS or (path.path != '/' and path.query):
                return self.send_body(404, b'{"status":"not_found"}')
            file, mime = ASSETS[path.path]
            self.send_body(200, (ROOT / file).read_bytes(), mime)
        def respond(self, status, payload):
            return self.send_body(status, json.dumps(payload, ensure_ascii=False).encode())

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
                matches = search(params.get('q', ''), catalog)
                return self.respond(200, {'status': 'ok' if matches else 'unsupported',
                                          'scope': 'reviewed_sample_catalog', 'candidates': matches})
            if path.path not in ('/api/reports', '/api/reader'):
                return self.respond(404, {'status': 'not_found'})
            if set(params) - ({'cik'} if path.path == '/api/reports' else {'cik', 'accession', 'version', 'unit'}):
                return self.respond(400, {'status': 'invalid_query'})
            cik = params.get('cik')
            if cik is not None and not CIK.fullmatch(cik):
                return self.respond(400, {'status': 'invalid_query'})
            if cik is not None and cik not in supported:
                return self.respond(404, {'status': 'unsupported'})
            if path.path == '/api/reports':
                if cik is None:
                    return self.respond(400, {'status': 'invalid_query'})
                return self.respond(200, {'reports': store.reports(cik)})
            accession, version = params.get('accession'), params.get('version')
            unit = params.get('unit', 'hundred_millions')
            if ((accession and (not cik or not ACCESSION.fullmatch(accession)))
                    or (version and (not accession or not SHA.fullmatch(version)))
                    or unit not in ('millions', 'hundred_millions')):
                return self.respond(400, {'status': 'invalid_query'})
            try:
                data = store.read(cik, accession, version)
                if data is None:
                    return self.respond(404, {'status': 'not_found'})
                divisor = '1000000' if unit == 'millions' else '100000000'
                return self.respond(200, read_model(data, divisor))
            except (EvidenceError, ValueError, KeyError):
                return self.respond(503, {'status': 'evidence_validation_failed'})
    return Handler


def serve(store, port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler_for(store))
    print('hiwd company local reader: http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
