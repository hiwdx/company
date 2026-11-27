"""Deterministic financial rules. No model, network, or inferred missing values."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


class EvidenceError(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise EvidenceError('invalid_number') from exc
    if not result.is_finite():
        raise EvidenceError('invalid_number')
    return result


def verify_fact(fact):
    required = ('concept', 'value', 'currency', 'unit', 'scale', 'period_kind', 'period_end',
                'accounting_standard', 'scope', 'version', 'source_url', 'anchor', 'context_id')
    if any(fact.get(key) is None or fact.get(key) == '' for key in required):
        raise EvidenceError('missing_evidence_or_context')
    if fact.get('status') != 'verified':
        raise EvidenceError('unverified_fact')
    if not fact['source_url'].startswith('https://www.sec.gov/Archives/edgar/data/320193/'):
        raise EvidenceError('unapproved_original_source')
    if fact['period_kind'] not in ('annual', 'instant'):
        raise EvidenceError('unsupported_period_kind')
    number(fact['value'])
    date.fromisoformat(fact['period_end'])
    if fact['period_kind'] == 'annual':
        start = date.fromisoformat(fact.get('period_start', ''))
        days = (date.fromisoformat(fact['period_end']) - start).days + 1
        if not 350 <= days <= 371:
            raise EvidenceError('not_an_annual_duration')
    return fact


def comparable(current, prior):
    verify_fact(current)
    verify_fact(prior)
    for key in ('concept', 'currency', 'unit', 'scale', 'period_kind', 'accounting_standard', 'scope', 'version'):
        if current[key] != prior[key]:
            raise EvidenceError('incomparable_' + key)
    current_end, prior_end = map(date.fromisoformat, (current['period_end'], prior['period_end']))
    if not 350 <= (current_end - prior_end).days <= 371:
        raise EvidenceError('incomparable_years')
    if current['period_kind'] == 'annual':
        current_start = date.fromisoformat(current['period_start'])
        if (current_start - prior_end).days != 1:
            raise EvidenceError('nonadjacent_reporting_periods')
        current_days = (current_end - current_start).days
        prior_days = (prior_end - date.fromisoformat(prior['period_start'])).days
        if current_days != prior_days:
            raise EvidenceError('incomparable_duration')


def yoy(current, prior):
    comparable(current, prior)
    denominator = number(prior['value'])
    if denominator <= 0:
        raise EvidenceError('zero_or_negative_base')
    if number(current['value']) < 0:
        raise EvidenceError('sign_change')
    with localcontext() as ctx:
        ctx.prec = 34
        value = (number(current['value']) / denominator - 1) * 100
        return {'value': str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
                'unit': '%', 'formula': '(current / prior - 1) × 100', 'rounding': 'ROUND_HALF_UP, 2dp',
                'inputs': [current['id'], prior['id']], 'version': current['version']}


def display_amount(fact, divisor='100000000'):
    verify_fact(fact)
    if divisor not in ('1000000', '100000000') or fact['unit'] != 'USD' or fact['currency'] != 'USD':
        raise EvidenceError('unsupported_display_unit')
    # value is in base USD; scale describes original iXBRL normalization only.
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
