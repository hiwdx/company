"""One foreground SEC attempt. Files and request evidence stay in --output."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwd_company.sec import SECClient, inspect_history, parse_rows

DATA = 'https://data.sec.gov'
ARCHIVE = 'https://www.sec.gov/Archives/edgar/data'
ISSUERS = {'AAPL': '0000320193', 'MSFT': '0000789019', 'NVDA': '0001045810', 'TSM': '0001046179'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--as-of', required=True, help='Local observation date in YYYY-MM-DD')
    cli.add_argument('--sample', choices=('full', 'repeat'), default='full')
    cli.add_argument('--ticker', action='append', choices=ISSUERS)
    args = cli.parse_args()
    client = SECClient(os.environ.get('SEC_USER_AGENT'))
    args.output.mkdir(parents=True, exist_ok=False)
    attempts = []

    def fetch(url, name, kind='json'):
        observed = datetime.now(timezone.utc).isoformat()
        result = client.get(url, kind)
        attempts.append({'url': url, 'at_utc': observed, 'status': result.status,
                         'http_status': result.http_status, 'mime': result.mime,
                         'bytes': len(result.body),
                         'sha256': hashlib.sha256(result.body).hexdigest() if result.body else None})
        print(name, result.status, result.http_status, len(result.body), flush=True)
        if result.status == 'ok':
            (args.output / name).write_bytes(result.body)
            return json.loads(result.body) if kind == 'json' else result.body
        return None

    coverage = {}
    try:
        for ticker, cik in ISSUERS.items():
            if (args.sample == 'repeat' and ticker != 'AAPL') or (args.ticker and ticker not in args.ticker):
                continue
            raw = fetch(f'{DATA}/submissions/CIK{cik}.json', f'{ticker}-submissions.json')
            if not raw or str(raw.get('cik')).zfill(10) != cik:
                break
            raw['observed_on'] = args.as_of
            forms = ('20-F', '6-K') if ticker == 'TSM' else ('10-K', '10-Q')
            coverage[ticker] = check = inspect_history(raw, cik=cik, start='2024-10-01',
                                                      end=args.as_of, forms=forms)
            if check['status'] == 'parse_failed':
                break
            rows = parse_rows(raw['filings']['recent'])
            facts = fetch(f'{DATA}/api/xbrl/companyfacts/CIK{cik}.json', f'{ticker}-facts.json')
            if not facts or str(facts.get('cik')).zfill(10) != cik:
                break
            if ticker == 'AAPL' and args.sample == 'full':
                wanted = check['matching_filings']
                rows = [r for form, count in [('10-K', 3), ('10-Q', 4)]
                        for r in [x for x in wanted if x['form'] == form][:count]]
            else:
                annual = forms[0]
                rows = [next(r for r in rows if r['form'] == annual)]
                if ticker == 'TSM':
                    rows += [next(r for r in check['matching_filings']
                                  if r['accessionNumber'] == '0001046179-26-000801' and r['form'] == '6-K')]
            for row in rows:
                accession = row['accessionNumber'].replace('-', '')
                primary = row['primaryDocument']
                html = fetch(f'{ARCHIVE}/{int(cik)}/{accession}/{primary}', primary, 'html')
                if client.stopped:
                    break
                exhibit = 'a2026q3consolidatedreport-.htm'
                if ticker == 'TSM' and row['form'] == '6-K' and html and exhibit.encode() in html:
                    fetch(f'{ARCHIVE}/{int(cik)}/{accession}/{exhibit}', exhibit, 'html')
            if client.stopped:
                break
    finally:
        if not attempts:
            return
        record = {'sample': args.sample, 'observed_on': args.as_of, 'transport': 'SECClient urllib HTTPS',
                  'environment': f'{platform.system()} {platform.machine()} Python {platform.python_version()}',
                  'minimum_interval_seconds': 1.1, 'stopped': client.stopped, 'attempts': attempts,
                  'apple_history': coverage.get('AAPL')}
        (args.output / 'probe-evidence.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
