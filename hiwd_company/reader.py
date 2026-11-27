"""Evidence-bound Chinese reader for the reviewed company catalog."""
from .catalog import issuers
from .domain import CURRENCIES, EvidenceError, display_amount, number, validate_claim, yoy
from .auto_facts import GROUPS
from .semantics import semantic_description


STATUS_LABELS = {
    'not_disclosed': '原文明确未披露', 'not_found': '未找到该报告', 'fetch_failed': '获取失败',
    'authorization_blocked': '访问授权阻塞', 'policy_blocked': '使用许可待确认', 'unsupported': '本原型暂未覆盖',
    'partial': '覆盖不完整', 'wrong_mime': '来源格式错误', 'parse_failed': '来源解析失败',
    'rate_limited': '来源限流', 'conflict': '来源冲突', 'unverified': '尚未核验',
    'document_verified': '原文已核验，财务数字待核验', 'financials_verified': '已核验财务事实'
}
PERIOD_NAMES = {'annual': '全年', 'quarter': '单季', 'year_to_date': '财年累计', 'instant': '期末余额'}
STANDARDS = {'US_GAAP': 'US GAAP', 'IFRS_IASB': 'IFRS（IASB）', 'IAS34_TAIWAN_FSC': 'IAS 34（台湾金融监督管理委员会认可）'}


def read_model(dataset, divisor='100000000'):
    doc = dataset['document']
    issuer = dataset['issuer']
    if 'securities' not in issuer:
        issuer = next((row for row in issuers() if row['cik'] == issuer['cik']), None)
        if not issuer:
            raise EvidenceError('unsupported_legacy_issuer')
    facts = {f['id']: f for f in dataset['facts']}
    slots = {(f['metric'], f.get('slot', 'current' if f['period_end'] == doc['report_end'] else 'prior')): f
             for f in facts.values() if f['metric'] != 'segment_revenue'}
    currency = doc.get('currency', next(iter(facts.values()))['currency'] if facts else None)
    unit = ('亿' if divisor == '100000000' else '百万') + CURRENCIES[currency]
    rows, claims = [], []
    for definition in GROUPS[dataset.get('metric_profile', 'industrial')]:
        metric, label, statement, meaning = definition.key, definition.label, definition.statement, definition.meaning
        current, prior = slots.get((metric, 'current')), slots.get((metric, 'prior'))
        if current is None:
            continue
        if current.get('semantic'):
            label = current.get('semantic_label') or label
            meaning = semantic_description(current['semantic'], meaning)
        elif metric == 'net_income' and current['concept'] == 'ProfitLoss':
            label = '合并净利润'
            meaning = '本期净利包含归属于母公司股东和非控股权益的利润。'
        calc, error = None, None
        if prior:
            try:
                calc = yoy(current, prior)
            except EvidenceError as exc:
                error = str(exc)
        else:
            error = 'comparison_unverified'
        current_display = display_amount(current, divisor)
        prior_display = display_amount(prior, divisor) if prior else None
        period = PERIOD_NAMES[current['period_kind']]
        if calc:
            value = calc['value']
            change = ('，与上年同期持平' if value == '0.00' else
                      '，较上年同期' + ('下降' if value.startswith('-') else '增长') + value.lstrip('-') + '%')
        else:
            change = '，暂无可核验的同比' if not prior else '，暂不计算同比'
        rows.append({'metric': metric, 'label': label, 'current': current, 'prior': prior,
                     'current_display': current_display, 'prior_display': prior_display, 'statement': statement,
                     'period_label': period, 'yoy': calc, 'calculation_error': error})
        claim = {'id': metric + '-explanation', 'kind': 'deterministic_explanation',
                 'text': f'{period}{label}为 {current_display} {unit}{change}。{meaning}',
                 'fact_ids': [current['id']] + ([prior['id']] if prior else []), 'calculation': calc}
        claims.append(validate_claim(claim, facts))
    components = [f for f in facts.values() if f['metric'] == 'segment_revenue']
    revenue = slots.get(('revenue', 'current'))
    if components and (not revenue or any(f['period_start'] != revenue['period_start'] for f in components)
                       or sum(number(f['value']) for f in components) != number(revenue['value'])):
        raise EvidenceError('revenue_components_do_not_reconcile')
    return {'brand': 'hiwd company', 'issuer': issuer, 'document': doc, 'currency': currency,
            'accounting_label': STANDARDS[doc['accounting_standard']],
            'dataset_kind': dataset['dataset_kind'], 'acquisition_mode': dataset['acquisition_mode'],
            'verification_status': doc.get('verification_status', 'financials_verified'),
            'rows': rows, 'claims': claims, 'unit': unit,
            'segments': [{'name': fact['segment'], 'amount': display_amount(fact, divisor), 'fact': fact}
                         for fact in components],
            'narrative': [{**item, 'source_url': doc['original_url']} for item in dataset.get('narrative', [])
                          if item['kind'] == 'business'],
            'metric_outcomes': dataset.get('metric_outcomes', []),
            'metric_profile': dataset.get('metric_profile', 'industrial'),
            'sections': {'announcements': {'status': 'partial', 'label': '近 90 天重大公告覆盖尚未核验。'},
                         'reporting': {'status': 'policy_blocked', 'label': '媒体来源使用许可待确认。'}},
            'status_labels': STATUS_LABELS}
