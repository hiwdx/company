"""Narrow Apple FY2026 iXBRL verifier. Never executes/serves original markup.

Only the six consolidated concepts in the reviewed profile are supported.
This is not a general PDF/XBRL parser. Unknown formats fail closed.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from decimal import Decimal
from .domain import EvidenceError, number

METRICS = [
    ('revenue', '收入', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'annual', '合并损益表', '公司在报告期内确认的销售收入，不等同现金到账。'),
    ('net_income', '净利润', 'NetIncomeLoss', 'annual', '合并损益表', '扣除经营成本、税项等后的会计利润，不等同可支配现金。'),
    ('operating_income', '经营利润', 'OperatingIncomeLoss', 'annual', '合并损益表', '经营收入扣除经营成本与费用后的利润，口径不同于净利润。'),
    ('operating_cash_flow', '经营现金流', 'NetCashProvidedByUsedInOperatingActivities', 'annual', '合并现金流量表', '经营活动产生的现金净额，与利润的确认时间和口径不同。'),
    ('assets', '总资产', 'Assets', 'instant', '合并资产负债表', '报告期末确认的资产账面总额，不是公司的市场价值。'),
    ('liabilities', '总负债', 'Liabilities', 'instant', '合并资产负债表', '报告期末确认的负债账面总额，不等同全部有息债务。'),
]


class InlineParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts, self.units, self.facts = {}, {}, []
        self.context = self.unit = None
        self.number_stack = []
        self.field = None
        self.blocked_active_depth = 0
        self.fields = {'xbrli:identifier', 'xbrli:startdate', 'xbrli:enddate', 'xbrli:instant'}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'iframe', 'object', 'embed'):
            self.blocked_active_depth += 1
            return
        if self.blocked_active_depth:
            return
        if tag == 'xbrli:context':
            self.context = {'id': attrs.get('id'), 'dimensioned': False}
        elif self.context is not None:
            if tag in ('xbrldi:explicitmember', 'xbrldi:typedmember'):
                self.context['dimensioned'] = True
            if tag in self.fields:
                self.field = tag
                self.context[tag] = ''
        if tag == 'xbrli:unit':
            self.unit = {'id': attrs.get('id'), 'text': ''}
        if tag == 'ix:nonfraction':
            # iXBRL can validly nest equivalent facts for different contexts.
            if len(self.number_stack) >= 32:
                raise EvidenceError('numeric_nesting_limit')
            self.number_stack.append({'attrs': attrs, 'text': ''})

    def handle_data(self, data):
        if self.blocked_active_depth:
            return
        if self.context is not None and self.field:
            self.context[self.field] += data
        if self.unit is not None:
            self.unit['text'] += data
        for fact in self.number_stack:
            fact['text'] += data

    def handle_endtag(self, tag):
        if tag in ('script', 'iframe', 'object', 'embed') and self.blocked_active_depth:
            self.blocked_active_depth -= 1
            return
        if self.blocked_active_depth:
            return
        if tag == self.field:
            self.field = None
        if tag == 'xbrli:context' and self.context is not None:
            key = self.context['id']
            if not key or key in self.contexts:
                raise EvidenceError('duplicate_or_missing_context')
            self.contexts[key] = self.context
            self.context = None
        if tag == 'xbrli:unit' and self.unit is not None:
            self.units[self.unit['id']] = self.unit['text'].strip()
            self.unit = None
        if tag == 'ix:nonfraction' and self.number_stack:
            self.facts.append(self.number_stack.pop())
        if len(self.facts) > 20000 or len(self.contexts) > 5000:
            raise EvidenceError('document_complexity_limit')


def parse_document(raw):
    if len(raw) > 8 * 1024 * 1024:
        raise EvidenceError('document_size_limit')
    text = raw.decode('utf-8-sig')
    if re.search(r'<!ENTITY|<!DOCTYPE[^>]*(?:SYSTEM|PUBLIC)', text, re.I):
        raise EvidenceError('external_entities_rejected')
    parser = InlineParser()
    parser.feed(text)
    if not parser.facts or not parser.contexts:
        raise EvidenceError('not_supported_inline_xbrl')
    return parser


def normalized(inline, units):
    attrs = inline['attrs']
    if attrs.get('format') != 'ixt:num-dot-decimal' or units.get(attrs.get('unitref')) != 'iso4217:USD':
        raise EvidenceError('unsupported_format_or_currency')
    scale = attrs.get('scale')
    if scale is None or not re.fullmatch(r'-?\d{1,2}', scale) or not -12 <= int(scale) <= 12:
        raise EvidenceError('unknown_scale')
    value = inline['text'].strip().replace(',', '').replace('\xa0', '')
    if not re.fullmatch(r'\d+(?:\.\d+)?', value):
        raise EvidenceError('unsupported_numeric_format')
    return number(value) * (Decimal(10) ** int(scale)) * (-1 if attrs.get('sign') == '-' else 1)


def import_report(html_bytes, facts_bytes, profile, mode='manual_import'):
    if mode not in ('manual_import', 'sec_official_single_run'):
        raise EvidenceError('unapproved_acquisition_mode')
    doc_sha = hashlib.sha256(html_bytes).hexdigest()
    if doc_sha != profile['original_sha256']:
        raise EvidenceError('unreviewed_document_version')
    if len(facts_bytes) > 8 * 1024 * 1024:
        raise EvidenceError('facts_size_limit')
    fact_sha = hashlib.sha256(facts_bytes).hexdigest()
    # Exact reviewed response hash plus raw original hash, not filenames.
    if fact_sha != profile['companyfacts_sha256']:
        raise EvidenceError('unreviewed_facts_version')
    raw_facts = json.loads(facts_bytes)
    if str(raw_facts.get('cik', '')).zfill(10) != profile['cik']:
        raise EvidenceError('issuer_mismatch')
    parsed = parse_document(html_bytes)
    records = []
    for metric, label, concept, kind, statement, meaning in METRICS:
        for fiscal_year in (2026, 2025):
            end = profile['periods'][str(fiscal_year)]['end']
            start = profile['periods'][str(fiscal_year)].get('start') if kind == 'annual' else None
            candidates = []
            for inline in parsed.facts:
                attrs = inline['attrs']
                if attrs.get('name') != 'us-gaap:' + concept:
                    continue
                context = parsed.contexts.get(attrs.get('contextref'), {})
                if context.get('dimensioned') or context.get('xbrli:identifier') != profile['cik']:
                    continue
                if kind == 'annual':
                    matches = context.get('xbrli:startdate') == start and context.get('xbrli:enddate') == end
                else:
                    matches = context.get('xbrli:instant') == end
                if matches:
                    candidates.append(inline)
            if not candidates:
                raise EvidenceError('missing_consolidated_fact_' + metric)
            values = {normalized(row, parsed.units) for row in candidates}
            if len(values) != 1:
                raise EvidenceError('conflicting_inline_values')
            value = values.pop()
            api = raw_facts['facts']['us-gaap'][concept]['units']['USD']
            matches = [row for row in api if row.get('accn') == profile['accession'] and row.get('end') == end
                       and row.get('start') == start and row.get('filed') == profile['published_on']
                       and row.get('form') == profile['form']]
            if not matches or {number(row['val']) for row in matches} != {value}:
                raise EvidenceError('original_api_mismatch_' + metric)
            chosen = candidates[0]['attrs']
            if not re.fullmatch(r'f-\d+', chosen.get('id', '')):
                raise EvidenceError('missing_original_anchor')
            records.append({'id': metric + '-' + str(fiscal_year), 'metric': metric, 'label': label,
                'concept': concept, 'value': str(value.quantize(Decimal(1))), 'display_original': candidates[0]['text'].strip(),
                'fiscal_year': fiscal_year, 'period_kind': kind, 'period_start': start, 'period_end': end,
                'currency': 'USD', 'unit': 'USD', 'scale': int(chosen['scale']),
                'accounting_standard': 'US_GAAP', 'scope': 'consolidated', 'version': profile['accession'],
                'source_url': profile['original_url'], 'anchor': chosen['id'], 'context_id': chosen['contextref'],
                'statement': statement, 'meaning': meaning, 'status': 'verified',
                'verification': 'inline XBRL context/value equals SEC companyfacts for same accession'})
    return {'schema_version': 1, 'dataset_kind': 'real_official_reviewed_snapshot', 'acquisition_mode': mode,
            'issuer': {'name': 'Apple Inc.', 'ticker': 'AAPL', 'market': 'US', 'exchange': 'Nasdaq', 'cik': profile['cik']},
            'document': profile, 'facts': records}


def load_raw(html_path, facts_path, profile_path, mode):
    return import_report(Path(html_path).read_bytes(), Path(facts_path).read_bytes(),
                         json.loads(Path(profile_path).read_text()), mode)
