"""Evidence-bound Chinese templates. Every numeric sentence names its inputs."""
from .domain import EvidenceError, display_amount, validate_claim, yoy
from .importer import METRICS


STATUS_LABELS = {'not_disclosed': '原文明确未披露', 'not_found': '尚未找到', 'fetch_failed': '获取失败',
                 'authorization_blocked': '访问授权阻塞', 'policy_blocked': '使用许可待确认',
                 'unsupported': '尚未支持', 'partial': '覆盖不完整', 'wrong_mime': '来源格式错误',
                 'parse_failed': '来源解析失败', 'rate_limited': '来源限流', 'conflict': '来源冲突'}


def read_model(dataset, divisor='100000000'):
    facts = {f['id']: f for f in dataset['facts']}
    rows, claims = [], []
    unit = '亿美元' if divisor == '100000000' else '百万美元'
    for metric, label, _concept, kind, _statement, meaning in METRICS:
        current, prior = facts[metric + '-2026'], facts[metric + '-2025']
        try:
            calc, calc_error = yoy(current, prior), None
        except EvidenceError as exc:
            calc, calc_error = None, str(exc)
        current_display, prior_display = display_amount(current, divisor), display_amount(prior, divisor)
        rows.append({'metric': metric, 'label': label, 'current': current, 'prior': prior,
            'current_display': current_display, 'prior_display': prior_display, 'unit': unit,
            'yoy': calc, 'calculation_error': calc_error, 'meaning': meaning})
        intro = '期末' if kind == 'instant' else '本财年'
        comparison = ('，较上年同期' + ('增加' if calc and not calc['value'].startswith('-') else '减少')
                      + calc['value'].lstrip('-') + '%') if calc else '；同比暂不计算，口径校验未通过'
        if calc and calc['value'] == '0.00':
            comparison = '，与上年同期持平'
        claim = {'id': metric + '-explanation', 'kind': 'deterministic_explanation',
            'text': intro + label + '为 ' + current_display + ' ' + unit + comparison + '。' + meaning,
            'fact_ids': [current['id'], prior['id']], 'calculation': calc}
        claims.append(validate_claim(claim, facts))
    return {'brand': 'hiwd company', 'issuer': dataset['issuer'], 'document': dataset['document'],
        'dataset_kind': dataset['dataset_kind'], 'acquisition_mode': dataset['acquisition_mode'],
        'rows': rows, 'claims': claims, 'unit': unit,
        'sections': {'announcements': {'status': 'partial', 'label': '仅核验当前 10-K，未整理近 90 天重大公告'},
                     'reporting': {'status': 'policy_blocked', 'label': '权威报道尚未接入，使用许可待确认'}},
        'management_statements': [], 'management_status': 'not_curated',
        'status_labels': STATUS_LABELS,
        'boundaries': ['本地已核验快照，非实时数据', '仅 Apple 一份 10-K，历史覆盖尚未完成',
                       '解释由确定性模板生成，无付费模型调用', '腾讯、港股、A 股和媒体后台均未启用']}
