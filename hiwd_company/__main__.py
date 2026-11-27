import argparse
import json
from pathlib import Path
from .domain import EvidenceError
from .importer import load_raw
from .store import Store

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='hiwd company local Apple evidence reader')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('serve')
    run.add_argument('--port', type=int, default=8765)
    run.add_argument('--db', default=str(ROOT / 'local-results/reader.sqlite'))
    imp = sub.add_parser('import-original', help='Offline import only; never declares a live fetch success')
    imp.add_argument('--html', required=True)
    imp.add_argument('--facts', required=True)
    imp.add_argument('--db', default=str(ROOT / 'local-results/manual.sqlite'))
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == 'import-original':
        payload = load_raw(args.html, args.facts, ROOT / 'data/apple-2026-profile.json', 'manual_import')
        result = store.put(payload)
        print(json.dumps({'status': result, 'mode': 'manual_import', 'facts': len(payload['facts']),
                          'live_api_success': False}))
    else:
        if store.read() is None:
            store.put(json.loads((ROOT / 'data/apple-2026-reviewed.json').read_text()))
        from .server import serve
        serve(store, args.port)


if __name__ == '__main__':
    main()
