"""Loopback-only prototype. No upload, URL fetch, or original-markup routes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .domain import EvidenceError
from .reader import read_model

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'/': ('app/index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app/app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('app/style.css', 'text/css; charset=utf-8'),
          '/manifest.webmanifest': ('app/manifest.webmanifest', 'application/manifest+json')}


def handler_for(store):
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
            if path.path == '/api/reader':
                query = parse_qs(path.query)
                if set(query) - {'unit'} or query.get('unit', ['hundred_millions']) not in (['millions'], ['hundred_millions']):
                    return self.send_body(400, b'{"status":"invalid_query"}')
                try:
                    data = store.read()
                    if data is None:
                        return self.send_body(503, b'{"status":"not_found"}')
                    divisor = '1000000' if query.get('unit') == ['millions'] else '100000000'
                    body = json.dumps(read_model(data, divisor), ensure_ascii=False).encode()
                    return self.send_body(200, body)
                except (EvidenceError, ValueError, KeyError):
                    return self.send_body(503, b'{"status":"evidence_validation_failed"}')
            if path.path not in ASSETS or path.query:
                return self.send_body(404, b'{"status":"not_found"}')
            file, mime = ASSETS[path.path]
            self.send_body(200, (ROOT / file).read_bytes(), mime)
    return Handler


def serve(store, port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler_for(store))
    print('hiwd company local reader: http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
