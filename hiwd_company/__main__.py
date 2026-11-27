import argparse
import json
import os
from pathlib import Path

from .catalog import ROOT
from .discovery import Research
from .importer import replay_snapshot
from .server import serve
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='hiwd company 上市公司财报阅读器')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('serve')
    run.add_argument('--port', type=int, default=8765)
    run.add_argument('--db', default=str(ROOT / 'local-results/reader.sqlite'))
    run.add_argument('--research-cache', default=str(ROOT / 'local-results/sec-research.sqlite'))
    run.add_argument('--allow-sec', action='store_true', help='仅在获许可的本机开启低频 SEC 请求')
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
        user_agent = os.environ.get('SEC_USER_AGENT') if args.allow_sec else None
        if args.allow_sec and not user_agent:
            parser.error('--allow-sec requires an authorized SEC_USER_AGENT')
        research = Research(args.research_cache, user_agent=user_agent)
        try:
            serve(store, args.port, research)
        finally:
            research.close()


if __name__ == '__main__':
    main()
