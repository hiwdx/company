"""Deterministic financial rules shared by all issuers."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from .sec import ACCESSION, PRIMARY


class EvidenceError(ValueError):
    pass


PERIOD_LIMITS = {'annual': (350, 371), 'quarter': (77, 103), 'year_to_date': (77, 290)}
CURRENCIES = {'USD': '美元', 'TWD': '新台币'}
SHA = re.compile(r'[a-f0-9]{64}')
ANCHOR = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,159}')
FORM_GROUPS = {'10-K': 'annual', '20-F': 'annual', '10-Q': 'interim', '6-K': 'foreign_report'}
STANDARDS = {'US_GAAP', 'IFRS_IASB', 'IAS34_TAIWAN_FSC'}


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise EvidenceError('invalid_number') from exc
    if not result.is_finite() or result.adjusted() not in range(-24, 25):
        raise EvidenceError('invalid_number')
    return result


def report_group(form):
    return FORM_GROUPS.get(form.removesuffix('/A')) if isinstance(form, str) else None


def evidence_url(url, cik=None, accession=None):
    match = re.fullmatch(
        r'https://www\.sec\.gov/Archives/edgar/data/([1-9]\d{0,9})/(\d{18})/([A-Za-z0-9._-]+)', url or '')
    if (not match or (cik is not None and match[1].zfill(10) != cik)
            or (accession is not None and match[2] != accession.replace('-', ''))
            or not PRIMARY.fullmatch(match[3]) or '..' in match[3]):
        raise EvidenceError('unapproved_original_source')
    return url


def duration(fact):
    return (date.fromisoformat(fact['period_end']) - date.fromisoformat(fact['period_start'])).days + 1


def verify_fact(fact):
    required = ('id', 'metric', 'concept', 'value', 'currency', 'unit', 'scale', 'period_kind', 'period_end',
                'accounting_standard', 'scope', 'version', 'source_url', 'anchor', 'context_id')
    if any(fact.get(key) is None or fact.get(key) == '' for key in required):
        raise EvidenceError('missing_evidence_or_context')
    if fact.get('status') != 'verified':
        raise EvidenceError('unverified_fact')
    evidence_url(fact['source_url'], fact.get('cik'), fact['version'])
    if not ANCHOR.fullmatch(fact['anchor']) or not ACCESSION.fullmatch(fact['version']):
        raise EvidenceError('invalid_fact_locator')
    if fact['currency'] not in CURRENCIES or fact['unit'] != fact['currency']:
        raise EvidenceError('unsupported_unit_or_currency')
    if type(fact['scale']) is not int or not -12 <= fact['scale'] <= 12:
        raise EvidenceError('unknown_scale')
    if fact['accounting_standard'] not in STANDARDS or fact['scope'] not in ('consolidated', 'segment'):
        raise EvidenceError('unapproved_accounting_scope')
    number(fact['value'])
    date.fromisoformat(fact['period_end'])
    kind = fact['period_kind']
    if kind == 'instant':
        if fact.get('period_start') is not None:
            raise EvidenceError('unexpected_instant_start')
    elif kind in PERIOD_LIMITS:
        low, high = PERIOD_LIMITS[kind]
        if not fact.get('period_start') or not low <= duration(fact) <= high:
            raise EvidenceError('incompatible_duration')
    else:
        raise EvidenceError('unsupported_period_kind')
    return fact


def comparable(current, prior):
    verify_fact(current)
    verify_fact(prior)
    for key in ('metric', 'concept', 'currency', 'unit', 'scale', 'period_kind', 'accounting_standard',
                'scope', 'version', 'source_url', 'cik', 'original_sha256', 'semantic'):
        if current.get(key) != prior.get(key):
            raise EvidenceError('incomparable_' + key)
    as_of, prior_end = map(date.fromisoformat, (current['period_end'], prior['period_end']))
    if not 350 <= (as_of - prior_end).days <= 371:
        raise EvidenceError('incomparable_years')
    kind = current['period_kind']
    if kind == 'instant':
        return
    start, prior_start = map(date.fromisoformat, (current['period_start'], prior['period_start']))
    if kind == 'annual' and (start - prior_end).days != 1:
        raise EvidenceError('nonadjacent_reporting_periods')
    calendar_aligned = ((start.month, start.day, as_of.month, as_of.day)
                        == (prior_start.month, prior_start.day, prior_end.month, prior_end.day))
    if abs(duration(current) - duration(prior)) > (1 if calendar_aligned else 0):
        raise EvidenceError('incomparable_duration')
    if not 350 <= (start - prior_start).days <= 371:
        raise EvidenceError('incomparable_years')


def yoy(current, prior):
    comparable(current, prior)
    denominator = number(prior['value'])
    if denominator <= 0:
        raise EvidenceError('zero_or_negative_base')
    if number(current['value']) < 0:
        raise EvidenceError('sign_change')
    with localcontext() as ctx:
        ctx.prec = 34
        value = ((number(current['value']) / denominator - 1) * 100).quantize(
            Decimal('.01'), rounding=ROUND_HALF_UP)
        return {'value': str(abs(value) if not value else value),
                'unit': '%', 'formula': '(current / prior - 1) × 100',
                'inputs': [current['id'], prior['id']], 'version': current['version']}


def display_amount(fact, divisor='100000000'):
    verify_fact(fact)
    if divisor not in ('1000000', '100000000'):
        raise EvidenceError('unsupported_display_unit')
    with localcontext() as ctx:
        ctx.prec = 34
        amount = number(fact['value']) / number(divisor)
        return format(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), ',.2f')


def validate_claim(claim, facts):
    if claim.get('kind') not in ('source_fact', 'deterministic_explanation', 'management_statement'):
        raise EvidenceError('unsupported_claim_kind')
    if not claim.get('fact_ids'):
        raise EvidenceError('claim_without_evidence')
    for fact_id in claim['fact_ids']:
        if fact_id not in facts:
            raise EvidenceError('claim_unknown_evidence')
        verify_fact(facts[fact_id])
    return claim
