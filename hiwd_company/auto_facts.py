"""Source-driven standard-taxonomy selection. No issuer profiles or expected values."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib

from .domain import CURRENCIES, PERIOD_LIMITS, EvidenceError, evidence_url, number, verify_fact
from .importer import METRICS, document_subject, normalized, parse_document
from .sec import ACCESSION


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    statement: str
    meaning: str
    kind: str
    gaap: tuple
    ifrs: tuple = ()


REVENUE = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet',
           'RevenueFromContractWithCustomerIncludingAssessedTax')
ALIASES = {
    'revenue': (REVENUE, ('RevenueFromContractsWithCustomers', 'Revenue')),
    'net_income': (('NetIncomeLoss', 'ProfitLoss'), ('ProfitLoss',)),
    'operating_income': (('OperatingIncomeLoss',), ('ProfitLossFromOperatingActivities',)),
    'operating_cash_flow': (('NetCashProvidedByUsedInOperatingActivities',), ('CashFlowsFromUsedInOperatingActivities',)),
    'assets': (('Assets',), ('Assets',)),
    'liabilities': (('Liabilities',), ('Liabilities',)),
}
INDUSTRIAL = tuple(Metric(key, label, statement, meaning,
                          'cash' if key == 'operating_cash_flow' else kind, *ALIASES[key])
                   for key, label, _, kind, statement, meaning in METRICS)
NET_INTEREST = Metric('net_interest', '净利息收入', '合并损益表', '计息资产收益扣除利息支出后的净额。', 'annual',
                      ('InterestIncomeExpenseNet',
                       'InterestAndDividendIncomeOperatingNetOfInterestExpense'))
NONINTEREST = Metric('noninterest', '非利息收入', '合并损益表', '可能包括服务费、交易和其他业务收入。', 'annual',
                     ('NoninterestIncome', 'NonInterestIncome'))
PROVISION = Metric('credit_provision', '信用损失拨备', '合并损益表', '在报告期确认的预期信用损失费用。', 'annual',
                   ('ProvisionForLoanLeaseAndOtherLosses', 'ProvisionForCreditLosses', 'ProvisionForLoanAndLeaseLosses'))
DEPOSITS = Metric('deposits', '总存款', '合并资产负债表', '客户存款在报告期末的账面余额。', 'instant',
                  ('Deposits', 'DepositLiabilities'))
INTEREST_INCOME = Metric('interest_income', '利息收入', '合并损益表', '报告期内确认的利息及适用的股息收入。', 'annual',
                         ('InterestAndDividendIncomeOperating', 'InterestIncomeOperating'))
BANK = (NET_INTEREST, NONINTEREST, PROVISION, INTEREST_INCOME, INDUSTRIAL[1], INDUSTRIAL[3], INDUSTRIAL[4],
        INDUSTRIAL[5], DEPOSITS)
GROUPS = {'industrial': INDUSTRIAL, 'depository': BANK}
VALID_SCHEMES = ('http://www.sec.gov/CIK', 'https://www.sec.gov/CIK')


@dataclass(frozen=True)
class Candidate:
    inline: dict
    concept: str
    currency: str
    start: date
    end: date

    @property
    def anchor(self):
        return self.inline['attrs']['id']

    @property
    def days(self):
        return (self.end - self.start).days + 1 if self.start else 0


def relevant_context(context, cik):
    return (not context.get('dimensioned')
            and context.get('xbrli:identifier', '').strip().zfill(10) == cik
            and context.get('identifier_scheme', '').rstrip('/') in VALID_SCHEMES)


def classify_issuer(sic):
    value = str(sic or '')
    if len(value) == 4 and value.isascii() and value.isdecimal() and value.startswith('60'):
        return 'depository'
    return 'industrial'


def supported_concepts(metrics, namespace):
    return {concept for metric in metrics for concept in (metric.gaap if namespace == 'us-gaap' else metric.ifrs)}


def fiscal_focus(parsed, cik):
    result = defaultdict(set)
    for row in parsed.metadata:
        attrs = row['attrs']
        if relevant_context(parsed.contexts.get(attrs.get('contextref'), {}), cik):
            result[attrs['name']].add(row['text'].strip())
    focus = result.get('dei:DocumentFiscalPeriodFocus', set())
    if len(focus) != 1 or focus - {'FY', 'Q1', 'Q2', 'Q3', 'Q4'}:
        return None
    return next(iter(focus))


def scan(parsed, cik, concepts, namespace):
    for inline in parsed.facts:
        attrs = inline['attrs']
        prefix, _, concept = (attrs.get('name') or '').partition(':')
        if (prefix != namespace or concept not in concepts or inline['hidden'] or not inline['in_table']
                or attrs.get('id') not in parsed.anchors or attrs['id'] in parsed.duplicate_anchors):
            continue
        ctx = parsed.contexts.get(attrs.get('contextref'), {})
        if not relevant_context(ctx, cik):
            continue
        unit = parsed.units.get(attrs.get('unitref'), '')
        currency = unit.removeprefix('iso4217:')
        if not unit.startswith('iso4217:') or currency not in CURRENCIES:
            continue
        start, end, instant = (ctx.get('xbrli:' + name) for name in ('startdate', 'enddate', 'instant'))
        if not ((start and end and not instant) or (instant and not start and not end)):
            continue
        try:
            yield Candidate(inline, concept, currency, date.fromisoformat(start) if start else None,
                            date.fromisoformat(end or instant))
        except ValueError:
            continue


def api_index(companyfacts, doc, namespace, concepts):
    result = defaultdict(set)
    by_tag = companyfacts.get('facts', {}).get(namespace, {})
    for concept in concepts:
        for currency, points in by_tag.get(concept, {}).get('units', {}).items():
            if currency not in CURRENCIES or not isinstance(points, list):
                continue
            for point in points:
                if (point.get('accn'), point.get('filed'), point.get('form')) != (
                        doc['accession'], doc['published_on'], doc['form']):
                    continue
                key = (concept, currency, point.get('start'), point.get('end'))
                result[key].add(number(point.get('val')))
    return result


def slot_kind(metric, form):
    if metric.kind == 'instant':
        return 'instant'
    if form.removesuffix('/A') != '10-Q':
        return 'annual'
    return 'year_to_date' if metric.kind == 'cash' else 'quarter'


def duration_allowed(row, kind, focus):
    if kind == 'instant':
        return row.start is None
    if row.start is None:
        return False
    lower, upper = PERIOD_LIMITS[kind]
    if kind == 'year_to_date':
        bounds = {'Q1': (77, 103), 'Q2': (155, 205), 'Q3': (230, 290)}
        if focus not in bounds:
            return False
        lower, upper = bounds[focus]
    return lower <= row.days <= upper


def select_group(rows, parsed, api):
    if not rows:
        return None, 'no_candidate'
    choices = defaultdict(list)
    for row in rows:
        choices[(row.concept, row.start, row.end)].append(row)
    if len(choices) != 1:
        return None, 'ambiguous_concept_or_period'
    group = next(iter(choices.values()))
    try:
        normalized_rows = [(normalized(row.inline, parsed.units, row.currency), row) for row in group]
    except EvidenceError:
        return None, 'unsupported_original_number'
    values = {value for value, _ in normalized_rows}
    if len(values) != 1:
        return None, 'conflicting_original_values'
    value, row = normalized_rows[0]
    key = (row.concept, row.currency, row.start.isoformat() if row.start else None, row.end.isoformat())
    matches = api.get(key)
    if not matches:
        return None, 'missing_same_filing_companyfacts'
    if matches != {value}:
        return None, 'companyfacts_mismatch'
    return (row, value), 'verified'


def choose_prior(rows, current, kind, form, focus):
    eligible = [row for row in rows if row.end < current.end and row.concept == current.concept
                and duration_allowed(row, kind, focus)]
    at_year = [row for row in eligible if 350 <= (current.end - row.end).days <= 371]
    if kind != 'instant':
        return [row for row in at_year if abs(row.days - current.days) <= 7]
    if form.removesuffix('/A') == '10-Q':
        # Interim balance sheets ordinarily use the previous fiscal year end.
        # Show a source comparison but the reader refuses a non-year-over-year change.
        comparison = max((row.end for row in eligible), default=None)
        return [row for row in eligible if row.end == comparison]
    return at_year


def fact_payload(selected, doc, cik, metric, kind, slot):
    row, value = selected
    attrs = row.inline['attrs']
    return verify_fact({
        'id': metric.key + '-' + slot, 'metric': metric.key, 'slot': slot, 'anchor': row.anchor,
        'concept': row.concept, 'value': format(value, 'f'), 'display_original': row.inline['text'].strip(),
        'period_kind': kind, 'period_start': row.start.isoformat() if row.start else None,
        'period_end': row.end.isoformat(), 'cik': cik, 'currency': row.currency, 'unit': row.currency,
        'scale': int(attrs['scale']), 'accounting_standard': doc['accounting_standard'], 'scope': 'consolidated',
        'version': doc['accession'], 'source_url': doc['original_url'], 'original_sha256': doc['original_sha256'],
        'context_id': attrs['contextref'], 'status': 'verified', 'verification': 'automatic_ixbrl_companyfacts_match',
    })


def extract(issuer, filing, html, companyfacts, *, observed_at, companyfacts_sha256):
    """Select and independently match facts for a filing already discovered in SEC submissions."""
    cik = issuer['cik']
    if str(companyfacts.get('cik', '')).zfill(10) != cik:
        raise EvidenceError('companyfacts_subject_mismatch')
    accession, form = filing['accessionNumber'], filing['form']
    base_form = form.removesuffix('/A')
    if base_form not in ('10-K', '10-Q') or not ACCESSION.fullmatch(accession):
        raise EvidenceError('unsupported_filing_form')
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filing['primaryDocument']}"
    evidence_url(url, cik, accession)
    end = date.fromisoformat(filing['reportDate'])
    if end > date.fromisoformat(filing['filingDate']):
        raise EvidenceError('period_after_filing')
    parsed = parse_document(html)
    sector = classify_issuer(issuer.get('sic'))
    metrics = GROUPS[sector]
    # Foreign packages are discovered, but automatic IASB accounting basis
    # verification is outside the accepted scope of this extractor.
    namespace = 'us-gaap'
    doc = {'accession': accession, 'form': form, 'published_on': filing['filingDate'],
           'report_end': end.isoformat(), 'original_url': url, 'original_sha256': hashlib.sha256(html).hexdigest(),
           'companyfacts_sha256': companyfacts_sha256, 'scope': 'consolidated',
           'accounting_standard': 'US_GAAP',
           'observed_at': observed_at, 'reviewed_on': observed_at[:10],
           'label': ('季报' if base_form == '10-Q' else '年报') + ' · ' + end.isoformat(),
           'is_amendment': form.endswith('/A'), 'verification_status': 'financials_verified'}
    document_subject(parsed, doc, cik)
    focus = fiscal_focus(parsed, cik)
    concepts = supported_concepts(metrics, namespace)
    candidates = list(scan(parsed, cik, concepts, namespace))
    api = api_index(companyfacts, doc, namespace, concepts)
    # Visible original Assets columns are a reporting-currency signal independent
    # of currency names in a stock ticker or on an exchange. Dual native candidates fail closed.
    currency_pool = {row.currency for row in candidates if row.concept == 'Assets' and row.end == end and not row.start
                     and (row.concept, row.currency, None, end.isoformat()) in api}
    if len(currency_pool) != 1:
        raise EvidenceError('absent_or_ambiguous_report_currency')
    doc['currency'] = currency_pool.pop()
    same_currency = [row for row in candidates if row.currency == doc['currency']]
    by_concept = defaultdict(list)
    for row in same_currency:
        by_concept[row.concept].append(row)
    records, outcomes = [], []
    for metric in metrics:
        concepts_for_metric = metric.gaap if namespace == 'us-gaap' else metric.ifrs
        if not concepts_for_metric:
            continue
        matching = [row for concept in concepts_for_metric for row in by_concept[concept]]
        kind = slot_kind(metric, form)
        # Ordered standard aliases handle preferred semantics. The explicitly
        # lower priority concept is used only when the higher priority one is absent.
        current_pool = [row for row in matching if row.end == end and duration_allowed(row, kind, focus)]
        if current_pool:
            first_concept = next(concept for concept in concepts_for_metric
                                 if any(row.concept == concept for row in current_pool))
            current_pool = [row for row in current_pool if row.concept == first_concept]
        chosen, status = select_group(current_pool, parsed, api)
        prior_status = 'not_selected'
        if chosen:
            records.append(fact_payload(chosen, doc, cik, metric, kind, 'current'))
            prior, prior_status = select_group(choose_prior(matching, chosen[0], kind, form, focus), parsed, api)
            if prior:
                records.append(fact_payload(prior, doc, cik, metric, kind, 'prior'))
        outcomes.append({'metric': metric.key, 'label': metric.label, 'status': status, 'prior_status': prior_status})
    if not records:
        doc['verification_status'] = 'document_verified'
    return {'schema_version': 3, 'dataset_kind': 'real_official_auto_verified', 'acquisition_mode': 'sec_on_demand',
            'issuer': issuer, 'document': doc, 'facts': records, 'narrative': [], 'metric_outcomes': outcomes,
            'metric_profile': sector}
