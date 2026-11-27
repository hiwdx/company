"""Parse a reviewed subset of inline XBRL without executing or serving it."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from decimal import Decimal
from .domain import ANCHOR, CURRENCIES, EvidenceError, evidence_url, number, verify_fact
from .sec import MAX_BODY

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
        self.anchors, self.metadata = set(), []
        self.non_numeric = None
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
        if ANCHOR.fullmatch(attrs.get('id') or ''):
            self.anchors.add(attrs['id'])
        if tag == 'ix:nonnumeric' and (attrs.get('name') or '').startswith('dei:'):
            self.non_numeric = {'attrs': attrs, 'text': ''}
        if tag == 'xbrli:context':
            self.context = {'id': attrs.get('id'), 'dimensioned': False}
        elif self.context is not None:
            if tag in ('xbrldi:explicitmember', 'xbrldi:typedmember'):
                self.context['dimensioned'] = True
            if tag == 'xbrldi:explicitmember':
                self.field = tag
                self.context.setdefault('members', []).append([attrs.get('dimension'), ''])
            if tag in self.fields:
                if tag in self.context:
                    raise EvidenceError('duplicate_context_field')
                if tag == 'xbrli:identifier':
                    self.context['identifier_scheme'] = attrs.get('scheme')
                self.field = tag
                self.context[tag] = ''
        if tag == 'xbrli:unit':
            self.unit = {'id': attrs.get('id'), 'text': '', 'measures': 0, 'compound': False}
        if self.unit is not None:
            if tag == 'xbrli:measure':
                self.unit['measures'] += 1
            if tag == 'xbrli:divide':
                self.unit['compound'] = True
        if tag == 'ix:nonfraction':
            # iXBRL can validly nest equivalent facts for different contexts.
            if len(self.number_stack) >= 32:
                raise EvidenceError('numeric_nesting_limit')
            self.number_stack.append({'attrs': attrs, 'text': ''})

    def handle_data(self, data):
        if self.blocked_active_depth:
            return
        if self.context is not None and self.field == 'xbrldi:explicitmember':
            self.context['members'][-1][1] += data
        elif self.context is not None and self.field:
            self.context[self.field] += data
        if self.unit is not None:
            self.unit['text'] += data
        if self.non_numeric is not None:
            self.non_numeric['text'] += data
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
        if tag == 'ix:nonnumeric' and self.non_numeric is not None:
            self.metadata.append(self.non_numeric)
            self.non_numeric = None
        if tag == 'xbrli:unit' and self.unit is not None:
            key = self.unit['id']
            if not key or key in self.units:
                raise EvidenceError('duplicate_or_missing_unit')
            self.units[key] = (self.unit['text'].strip() if self.unit['measures'] == 1
                               and not self.unit['compound'] else '')
            self.unit = None
        if tag == 'ix:nonfraction' and self.number_stack:
            self.facts.append(self.number_stack.pop())
        if len(self.facts) > 20000 or len(self.contexts) > 5000:
            raise EvidenceError('document_complexity_limit')


def parse_document(raw):
    if len(raw) > MAX_BODY:
        raise EvidenceError('document_size_limit')
    text = raw.decode('utf-8-sig')
    if re.search(r'<!ENTITY|<!DOCTYPE[^>]*(?:SYSTEM|PUBLIC)', text, re.I):
        raise EvidenceError('external_entities_rejected')
    parser = InlineParser()
    parser.feed(text)
    parser.close()
    if parser.number_stack or parser.blocked_active_depth or parser.context or parser.unit:
        raise EvidenceError('incomplete_inline_markup')
    if not parser.facts or not parser.contexts:
        raise EvidenceError('not_supported_inline_xbrl')
    return parser


def normalized(inline, units, currency='USD'):
    attrs = inline['attrs']
    if currency not in CURRENCIES or units.get(attrs.get('unitref')) != 'iso4217:' + currency:
        raise EvidenceError('unsupported_format_or_currency')
    transform = attrs.get('format')
    if transform not in ('ixt:num-dot-decimal', 'ixt:numdotdecimal', 'ixt:num-dot-decimal-in'):
        raise EvidenceError('unsupported_format_or_currency')
    sign = attrs.get('sign')
    if sign not in (None, '-'):
        raise EvidenceError('unsupported_sign')
    scale = attrs.get('scale')
    if scale is None or not re.fullmatch(r'-?\d{1,2}', scale) or not -12 <= int(scale) <= 12:
        raise EvidenceError('unknown_scale')
    value = inline['text'].strip()
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', value):
        raise EvidenceError('unsupported_numeric_format')
    return number(value.replace(',', '')) * Decimal(10) ** int(scale) * (-1 if sign == '-' else 1)


def verified_index(raw, document, cik):
    if str(raw.get('cik', '')).zfill(10) != cik:
        raise EvidenceError('issuer_mismatch')
    from .sec import parse_rows
    rows = parse_rows(raw['filings']['recent'])
    for row in rows:
        accession = row['accessionNumber']
        if accession == document['accession']:
            suffix = '/' + row['primaryDocument']
            if (row['form'] == document['form'] and row['filingDate'] == document['published_on']
                    and row['reportDate'] == document['report_end'] and document['original_url'].endswith(suffix)):
                return
            raise EvidenceError('filing_index_mismatch')
    raise EvidenceError('missing_accession_in_index')


def document_subject(parsed, document, cik):
    identity = {}
    for meta in parsed.metadata:
        attrs = meta['attrs']
        context = parsed.contexts.get(attrs.get('contextref'), {})
        if context.get('xbrli:identifier') != cik or context.get('dimensioned'):
            continue
        identity.setdefault(attrs.get('name'), set()).add(meta['text'].strip())
    if identity.get('dei:EntityCentralIndexKey') != {cik} or identity.get('dei:DocumentType') != {document['form']}:
        raise EvidenceError('document_subject_or_form_mismatch')
    # The filing index supplies the canonical date. XBRL includes representations
    # such as "June 30, 2026"; validate the context end below without guessing locale.


def check_companyfacts(raw_facts, document, inline, value, fact, *, required):
    concept = inline['attrs']['name']
    ns, name = concept.split(':', 1)
    api = raw_facts.get('facts', {}).get(ns, {}).get(name, {}).get('units', {}).get(fact['unit'], [])
    matches = [row for row in api if row.get('accn') == document['accession']
               and row.get('end') == fact['period_end'] and row.get('start') == fact['period_start']
               and row.get('filed') == document['published_on'] and row.get('form') == document['form']]
    if matches and {number(row['val']) for row in matches} != {value}:
        raise EvidenceError('original_api_mismatch_' + fact['metric'])
    if required and not matches:
        raise EvidenceError('missing_companyfacts_' + fact['metric'])
    return bool(matches)


def verified_fact(parsed, indexed, spec, document, cik, raw_facts):
    inline = indexed.get(spec['anchor'])
    if inline is None:
        raise EvidenceError('missing_or_duplicate_original_anchor')
    attrs = inline['attrs']
    context = parsed.contexts.get(attrs.get('contextref'), {})
    currency = document['currency']
    if (context.get('xbrli:identifier') != cik
            or context.get('identifier_scheme', '').rstrip('/') not in ('http://www.sec.gov/CIK', 'https://www.sec.gov/CIK')
            or context.get('dimensioned') != (spec.get('metric') == 'segment_revenue')):
        raise EvidenceError('fact_subject_or_scope_mismatch')
    if context.get('dimensioned') and context.get('members') != spec.get('members'):
        raise EvidenceError('segment_member_mismatch')
    if attrs.get('name') != spec['concept']:
        raise EvidenceError('original_concept_mismatch')
    start = context.get('xbrli:startdate')
    end = context.get('xbrli:enddate') or context.get('xbrli:instant')
    if (start, end) != (spec.get('period_start'), spec['period_end']):
        raise EvidenceError('original_period_mismatch')
    value = normalized(inline, parsed.units, currency)
    if value != number(spec['expected']):
        raise EvidenceError('original_checkpoint_mismatch_' + spec['metric'])
    if not spec['concept'].startswith('us-gaap:' if document['accounting_standard'] == 'US_GAAP' else 'ifrs-full:'):
        raise EvidenceError('taxonomy_mismatch')
    fact = {key: value for key, value in spec.items() if key not in ('expected', 'require_api')}
    fact.update({'cik': cik, 'concept': spec['concept'].split(':', 1)[1], 'value': format(value, 'f'),
                 'display_original': inline['text'].strip(), 'currency': currency, 'unit': currency,
                 'scale': int(attrs['scale']), 'accounting_standard': document['accounting_standard'],
                 'scope': 'segment' if context.get('dimensioned') else 'consolidated', 'version': document['accession'], 'original_sha256': document['original_sha256'],
                 'source_url': document['original_url'], 'context_id': attrs['contextref'], 'status': 'verified',
                 'period_start': start})
    matched = fact['scope'] == 'consolidated' and check_companyfacts(
        raw_facts, document, inline, value, fact, required=spec.get('require_api', False))
    fact['verification'] = 'ixbrl_companyfacts_and_checkpoint' if matched else 'ixbrl_and_reviewed_statement_checkpoint'
    return verify_fact(fact)


def import_report(html_bytes, facts_bytes, profile, mode='manual_import', *, raw_index=None):
    if mode not in ('manual_import', 'sec_adapter_snapshot'):
        raise EvidenceError('unapproved_acquisition_mode')
    document = profile['document']
    issuer = profile['issuer']
    cik = issuer['cik']
    evidence_url(document['original_url'], cik, document['accession'])
    if hashlib.sha256(html_bytes).hexdigest() != document['original_sha256']:
        raise EvidenceError('unreviewed_document_version')
    if len(facts_bytes) > MAX_BODY:
        raise EvidenceError('facts_size_limit')
    raw_facts = json.loads(facts_bytes) if facts_bytes else {}
    if raw_facts and str(raw_facts.get('cik', '')).zfill(10) != cik:
        raise EvidenceError('issuer_mismatch')
    if raw_index is not None:
        verified_index(raw_index, document, cik)
    if mode == 'sec_adapter_snapshot' and raw_index is None:
        raise EvidenceError('missing_filing_index')
    if profile.get('index_only'):
        raise EvidenceError('index_only_no_financial_parse')
    parsed = parse_document(html_bytes)
    document_subject(parsed, document, cik)
    indexed = {}
    for inline in parsed.facts:
        anchor = inline['attrs'].get('id')
        if anchor:
            indexed[anchor] = None if anchor in indexed else inline
    records = [verified_fact(parsed, indexed, spec, document, cik, raw_facts) for spec in profile['facts']]
    narrative = profile.get('narrative', [])
    if any(item['anchor'] not in parsed.anchors for item in narrative):
        raise EvidenceError('missing_narrative_source')
    return {'schema_version': 2, 'dataset_kind': 'real_official_reviewed_snapshot',
            'acquisition_mode': mode, 'issuer': issuer, 'document': document,
            'facts': records, 'narrative': narrative}


def load_raw(html_path, facts_path, profile_path, mode, *, index_path=None):
    return import_report(Path(html_path).read_bytes(), Path(facts_path).read_bytes() if facts_path else b'',
                         json.loads(Path(profile_path).read_text()), mode,
                         raw_index=json.loads(Path(index_path).read_bytes()) if index_path else None)


def replay_snapshot(snapshot, html_bytes, facts_bytes, raw_index, attachments=None, *, mode='manual_import'):
    """Replay the reviewed source selection with locally obtained official bytes."""
    doc, issuer = snapshot['document'], snapshot['issuer']
    if doc['verification_status'] == 'document_verified':
        verified_index(raw_index, doc, issuer['cik'])
        if hashlib.sha256(html_bytes).hexdigest() != doc['original_sha256']:
            raise EvidenceError('unreviewed_document_version')
        for link in doc.get('attachments', []):
            name = link['url'].rsplit('/', 1)[1]
            raw = (attachments or {}).get(name, b'')
            if hashlib.sha256(raw).hexdigest() != link['sha256'] or name.encode() not in html_bytes:
                raise EvidenceError('unreviewed_attachment_version')
        return {**snapshot, 'acquisition_mode': mode}
    ns = 'us-gaap' if doc['accounting_standard'] == 'US_GAAP' else 'ifrs-full'
    specs = []
    for fact in snapshot['facts']:
        fields = ('id', 'metric', 'slot', 'anchor', 'period_kind', 'period_start', 'period_end', 'segment', 'members')
        specs.append({**{key: fact[key] for key in fields if key in fact},
                      'concept': f"{ns}:{fact['concept']}", 'expected': fact['value'],
                      'require_api': fact['verification'] == 'ixbrl_companyfacts_and_checkpoint'})
    profile = {'document': doc, 'issuer': issuer, 'narrative': snapshot.get('narrative', []), 'facts': specs}
    return import_report(html_bytes, facts_bytes, profile, mode, raw_index=raw_index)
