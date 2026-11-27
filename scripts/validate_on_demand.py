"""Exercise official discovery and capture sanitized evidence for supplied queries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiwd_company.discovery import Research
from hiwd_company.reader import read_model


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('queries', nargs='+')
    cli.add_argument('--cache', type=Path, required=True)
    cli.add_argument('--evidence', type=Path, required=True)
    args = cli.parse_args()
    research = Research(args.cache, user_agent=os.environ.get('SEC_USER_AGENT'))
    evidence = {'outcomes': [], 'source_requests': []}
    try:
        for query in args.queries:
            match = research.search(query)
            exact = [row for row in match['candidates'] if query.upper() in row['matched_tickers']]
            if len(exact or match['candidates']) != 1:
                evidence['outcomes'].append({'query': query, 'status': 'needs_disambiguation',
                                             'candidates': match['candidates']})
                continue
            issuer = (exact or match['candidates'])[0]
            result = research.run(issuer['cik'])
            report = research.store.read(issuer['cik'], result.get('selected_accession')) if result.get('selected_accession') else None
            result['query'] = query
            if report and result['verification'] in ('financials_verified', 'document_verified'):
                model = read_model(report)
                result['facts'] = report['facts']
                result['model_row_count'] = len(model['rows'])
            print(query, issuer['cik'], result['verification'], len(result.get('facts', [])), result.get('diagnostic', ''),
                  flush=True)
            evidence['outcomes'].append(result)
    finally:
        evidence['source_requests'] = research.source.attempts
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        research.close()


if __name__ == '__main__':
    main()
