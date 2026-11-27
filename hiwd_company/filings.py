"""SEC submissions directory validation and disclosure windows."""
from datetime import date, timedelta
import re

from .domain import EvidenceError, evidence_url
from .sec import HISTORY_FILE, PRIMARY, parse_rows


PERIODIC = frozenset(('10-K', '10-Q', '20-F', '40-F'))
EVENT = frozenset(('8-K', '6-K'))
ITEM_NAMES = {
    '1.01': '签署重大正式协议', '1.02': '终止重大正式协议',
    '1.03': '破产或接管', '1.05': '重大网络安全事件',
    '2.01': '完成资产收购或处置', '2.02': '经营结果及财务状况', '2.03': '新增直接财务义务',
    '2.04': '触发义务加速或增加', '2.05': '退出或处置活动成本', '2.06': '重大减值',
    '3.01': '上市规则或退市事项', '3.02': '未注册股本销售', '3.03': '证券持有人权利变更',
    '4.01': '审计机构变更', '4.02': '先前财报或审计不再可依赖',
    '5.01': '控制权变更', '5.02': '董事、高管或薪酬安排', '5.03': '章程或财年变更',
    '5.07': '证券持有人表决结果', '7.01': 'Regulation FD 披露',
    '8.01': '其他事项', '9.01': '财务报表及附件',
}


def iso(text):
    value = date.fromisoformat(text)
    if value.isoformat() != text:
        raise ValueError('noncanonical_sec_date')
    return value


def filing_url(cik, row):
    accession = row['accessionNumber']
    url = (f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/'
           + accession.replace('-', '') + '/' + row['primaryDocument'])
    return evidence_url(url, cik, accession)


def read_page(payload):
    rows = parse_rows(payload)
    for row, items in zip(rows, payload.get('items', [''] * len(rows))):
        filed = iso(row['filingDate'])
        ending = iso(row['reportDate']) if row['reportDate'] else None
        form = row['form'].removesuffix('/A')
        if form in PERIODIC and (not ending or ending > filed):
            raise ValueError('invalid_financial_period')
        if form in PERIODIC | EVENT and not PRIMARY.fullmatch(row['primaryDocument']):
            raise ValueError('invalid_primary_filing_path')
        if not isinstance(items, str):
            raise ValueError('invalid_item_codes')
        row['item_codes'] = sorted(set(re.findall(r'(?<![\d.])[1-9]\.\d{2}(?![\d.])', items)))
    return rows


def inspect_manifest(index, cik):
    if str(index.get('cik', '')).zfill(10) != cik:
        raise ValueError('submissions_issuer_mismatch')
    filings = index['filings']
    recent = read_page(filings['recent'])
    if not recent or not isinstance(filings['files'], list):
        raise ValueError('submissions_manifest_missing')
    entries = {}
    for item in filings['files']:
        name = item['name']
        match = HISTORY_FILE.fullmatch(name)
        first, last = iso(item['filingFrom']), iso(item['filingTo'])
        if (not match or match['cik'] != cik or first > last or name in entries
                or type(item['filingCount']) is not int or item['filingCount'] <= 0):
            raise ValueError('submissions_manifest_invalid')
        page_number = int(name.rsplit('-', 1)[1].split('.', 1)[0])
        entries[name] = (first, last, item['filingCount'], page_number)
    ordered = sorted(entries.values(), key=lambda item: item[3])
    if [row[3] for row in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError('submissions_manifest_sequence_gap')
    recent_from = min(iso(row['filingDate']) for row in recent)
    if ordered and (ordered[0][1] > recent_from
                    or any(older[1] > newer[0] for newer, older in zip(ordered, ordered[1:]))):
        raise ValueError('submissions_manifest_overlap_or_order')
    return recent, entries


def collect_window(index, cik, observed_on, start, fetch_page):
    """Read every declared intersecting page. Observation derives from retrieval, not the UI."""
    since, until = iso(start), iso(observed_on)
    if since > until:
        raise ValueError('invalid_window_order')
    recent, manifest = inspect_manifest(index, cik)
    rows, requested, missing, rejected, loaded = list(recent), [], [], [], []
    for name, (first, last, count, _) in sorted(manifest.items(), key=lambda item: item[1][3]):
        if not (first <= until and last >= since):
            continue
        requested.append(name)
        if missing:
            missing.append(name)
            continue
        result = fetch_page(name)
        if result is None:
            missing.append(name)
            continue
        page = read_page(result)
        dt = [iso(row['filingDate']) for row in page]
        if len(page) != count or not dt or min(dt) != first or max(dt) != last:
            rejected.append({'name': name, 'reason': 'submissions_page_receipt_mismatch',
                             'declared_count': count, 'actual_count': len(page),
                             'declared_from': first.isoformat(), 'declared_to': last.isoformat(),
                             'actual_from': min(dt).isoformat() if dt else None,
                             'actual_to': max(dt).isoformat() if dt else None})
            missing.append(name)
            continue
        rows.extend(page)
        loaded.append(name)
    accessions = {row['accessionNumber'] for row in rows}
    if len(accessions) != len(rows):
        raise ValueError('submissions_duplicate_accession')
    recent_from = min(iso(row['filingDate']) for row in recent)
    coverage_from = min([recent_from] + [detail[0] for name, detail in manifest.items() if name in requested and name not in missing])
    all_known_from = min([recent_from] + [detail[0] for detail in manifest.values()])
    return {
        'start': start, 'end': observed_on, 'recent_from': recent_from.isoformat(),
        'coverage_from': coverage_from.isoformat(), 'declared_history_from': all_known_from.isoformat(),
        'manifest': [{'name': name, 'from': first.isoformat(), 'to': last.isoformat(), 'count': n}
                     for name, (first, last, n, _) in manifest.items()],
        'requested_pages': requested, 'loaded_pages': loaded, 'missing_pages': missing,
        'rejected_pages': rejected, 'recent_count': len(recent),
        'complete': not missing and coverage_from <= since,
        'rows': sorted((row for row in rows if since <= iso(row['filingDate']) <= until),
                       key=lambda row: (row['filingDate'], row['accessionNumber']), reverse=True)
    }


def classify_filing(cik, row):
    form = row['form']
    return {'accession': row['accessionNumber'], 'form': form, 'published_on': row['filingDate'],
            'report_end': row['reportDate'], 'original_url': filing_url(cik, row),
            'is_amendment': form.endswith('/A')}


def periodic_filings(window, cik):
    recent = [row for row in window['rows'] if row['form'].removesuffix('/A') in PERIODIC]
    recent.sort(key=lambda row: (row['reportDate'], row['filingDate'], row['accessionNumber']), reverse=True)
    catalog = [classify_filing(cik, row) for row in recent]
    base_accessions = {(r['report_end'], r['form']): r['accession'] for r in reversed(catalog) if not r['is_amendment']}
    for record in catalog:
        if record['is_amendment']:
            record['base_accession'] = base_accessions.get((record['report_end'], record['form'].removesuffix('/A')))
    return catalog, recent


def announcement_window(window, cik):
    start = iso(window['end']) - timedelta(days=89)
    entries = []
    for row in window['rows']:
        form = row['form'].removesuffix('/A')
        if form not in EVENT or iso(row['filingDate']) < start:
            continue
        record = classify_filing(cik, row)
        codes = row['item_codes'] if form == '8-K' else []
        record['items'] = [{'code': code, 'label': ITEM_NAMES.get(code, 'SEC 披露事项')} for code in codes]
        record['summary'] = ('公司向 SEC 报送外国私人发行人报告。' if form == '6-K' else
                             '公司向 SEC 提交当前报告。')
        entries.append(record)
    return {'start': start.isoformat(), 'end': window['end'],
            'state': 'observed' if (iso(window['recent_from']) <= start
                                    or (not window['missing_pages'] and iso(window['coverage_from']) <= start)) else 'partial',
            'entries': entries}
