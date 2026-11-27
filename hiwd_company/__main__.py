import argparse
import json
from pathlib import Path

from .catalog import ROOT
from .importer import replay_snapshot
from .server import serve
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='hiwd company 上市公司财报阅读器')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('serve')
    run.add_argument('--port', type=int, default=8765)
    run.add_argument('--db', default=str(ROOT / 'local-results/reader.sqlite'))
    imp = commands.add_parser('import-original', help='本地原文重放')
    imp.add_argument('--snapshot', type=Path, required=True)
    imp.add_argument('--html', type=Path, required=True)
    imp.add_argument('--facts', type=Path)
    imp.add_argument('--index', type=Path, required=True)
    imp.add_argument('--attachment', type=Path, action='append', default=[])
    imp.add_argument('--supersedes', nargs=2, metavar=('ACCESSION', 'SHA256'))
    imp.add_argument('--db', default=str(ROOT / 'local-results/manual.sqlite'))
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == 'import-original':
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        payload = replay_snapshot(snapshot, args.html.read_bytes(), args.facts.read_bytes() if args.facts else b'',
                                  json.loads(args.index.read_bytes()), {p.name: p.read_bytes() for p in args.attachment})
        result = store.put(payload, tuple(args.supersedes) if args.supersedes else None)
        print(json.dumps({'status': result, 'mode': 'manual_import', 'facts': len(payload['facts']),
                          'verified': payload['document']['verification_status'], 'live_api_success': False}))
    else:
        for path in sorted((ROOT / 'data/reports').glob('*.json')):
            store.put(json.loads(path.read_text(encoding='utf-8')), seed=True)
        serve(store, args.port)


if __name__ == '__main__':
    main()
