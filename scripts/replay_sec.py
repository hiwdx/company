"""Replay reviewed snapshots against SECClient receipts and local official files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwd_company.catalog import ROOT
from hiwd_company.importer import replay_snapshot
from hiwd_company.reader import read_model
from hiwd_company.store import Store


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--batch', action='append', type=Path, required=True)
    cli.add_argument('--db', type=Path, required=True)
    cli.add_argument('--evidence', type=Path)
    args = cli.parse_args()
    store = Store(args.db)
    evidence = {'transport': 'SECClient', 'reports': []}
    for batch in args.batch:
        receipt = json.loads((batch / 'probe-evidence.json').read_bytes())
        fetched = {attempt['url']: attempt for attempt in receipt['attempts'] if attempt['status'] == 'ok'}

        def read(url, filename):
            raw = (batch / filename).read_bytes()
            if url not in fetched or hashlib.sha256(raw).hexdigest() != fetched[url]['sha256']:
                raise ValueError('file_does_not_match_adapter_receipt')
            return raw

        for path in sorted((ROOT / 'data/reports').glob('*.json')):
            reviewed = json.loads(path.read_text())
            doc, issuer = reviewed['document'], reviewed['issuer']
            url = doc['original_url']
            if url not in fetched:
                continue
            ticker, cik = issuer['securities'][0]['ticker'], issuer['cik']
            html = read(url, url.rsplit('/', 1)[-1])
            index = json.loads(read(f'https://data.sec.gov/submissions/CIK{cik}.json', f'{ticker}-submissions.json'))
            facts = read(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', f'{ticker}-facts.json')
            attachments = {}
            for link in doc.get('attachments', []):
                filename = link['url'].rsplit('/', 1)[-1]
                attachments[filename] = read(link['url'], filename)
            replayed = replay_snapshot(reviewed, html, facts, index, attachments, mode='sec_adapter_snapshot')
            if replayed != reviewed:
                raise ValueError('replay_does_not_match_reviewed_snapshot')
            action = store.put(replayed)
            model = read_model(store.read(cik, doc['accession'], doc['original_sha256']))
            row = {'batch': batch.name, 'ticker': ticker, 'accession': doc['accession'], 'store': action,
                   'verified_facts': len(replayed['facts']), 'reader_rows': len(model['rows']),
                   'verification': model['verification_status']}
            evidence['reports'].append(row)
            print(json.dumps(row, ensure_ascii=False))
    if not evidence['reports']:
        raise ValueError('no_reviewed_reports_replayed')
    if args.evidence:
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
