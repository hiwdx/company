"""Reviewed HK/CN identity and link-only entries. No document fetch."""
import json
import re
from urllib.parse import urlsplit

from .catalog import ROOT, normalize


VENUES = {'XHKG': ('HK', 'HK', 5), 'XSHG': ('CN', 'SH', 6),
          'XSHE': ('CN', 'SZ', 6), 'XBSE': ('CN', 'BJ', 6)}
NAVIGATION_HOSTS = {'www.tencent.com', 'www.alibabagroup.com', 'www.moutaichina.com', 'www.icbc-ltd.com'}
HOME_ONLY = {'www.sse.com.cn', 'www.szse.cn', 'www.bse.cn', 'www.cninfo.com.cn'}


def navigation_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc not in NAVIGATION_HOSTS | HOME_ONLY
            or parsed.fragment or parsed.query or (parsed.netloc in HOME_ONLY and parsed.path != '/')):
        raise ValueError('unapproved_market_navigation')
    return url


def validated(data):
    issuer_ids, securities = set(), set()
    for issuer in data:
        key = issuer['issuer_id']
        if not re.fullmatch(r'issuer:[a-z0-9-]+', key) or key in issuer_ids or 'cik' in issuer:
            raise ValueError('invalid_market_issuer_identity')
        issuer_ids.add(key)
        for security in issuer['securities']:
            market, suffix, width = VENUES[security['mic']]
            code, isin = security['code'], security.get('isin')
            if (not re.fullmatch(rf'[0-9]{{{width}}}', code) or security['market'] != market
                    or security['ticker'] != f'{code}.{suffix}' or security['ticker'] in securities
                    or (isin is not None and not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', isin))):
                raise ValueError('invalid_market_security')
            securities.add(security['ticker'])
        for source in issuer['sources']:
            navigation_url(source['url'])
    return data


def market_issuers():
    return validated(json.loads((ROOT / 'data/market-navigation.json').read_text(encoding='utf-8')))


def search_market(query, catalog):
    term = normalize(query)
    if not term:
        return []
    matches = []
    for issuer in catalog:
        names = [normalize(value) for value in (issuer['name'], issuer['label'], *issuer['aliases'])]
        securities = [security for security in issuer['securities']
                      if term in (normalize(security['ticker']), security['code'], normalize(security.get('isin') or ''))]
        if securities or term in names or (len(term) >= 2 and any(term in name for name in names)):
            matches.append({**issuer, 'kind': 'market_navigation', 'status': 'authorization_blocked',
                            'matched_tickers': [security['ticker'] for security in securities]})
    return matches
