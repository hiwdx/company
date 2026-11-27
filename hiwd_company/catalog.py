"""Small reviewed issuer catalog. A security symbol is never used as an issuer key."""
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
CIK = re.compile(r'\d{10}')


def issuers():
    return json.loads((ROOT / 'data/issuers.json').read_text(encoding='utf-8'))


def normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(re.findall(r'[^\W_]+', text, re.UNICODE))


def search(query, catalog=None):
    catalog = issuers() if catalog is None else catalog
    term = normalize(query)
    if not term:
        return []
    results = []
    for issuer in catalog:
        securities = [stock for stock in issuer['securities'] if normalize(stock['ticker']) == term]
        names = [normalize(item) for item in (issuer['name'], issuer['label'], *issuer['aliases'])]
        name_match = term in names
        partial = len(term) >= 2 and any(term in name for name in names)
        if securities or name_match or partial:
            results.append((0 if securities else 1 if name_match else 2, issuer['cik'],
                            {**issuer, 'matched_tickers': [stock['ticker'] for stock in securities]}))
    return [entry for _, _, entry in sorted(results)]
