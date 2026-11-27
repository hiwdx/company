"""Conservative US GAAP row and statement evidence for automatic facts."""
import re


def words(label):
    label = re.sub(r'\s*\([a-z0-9]\)\s*$', '', label, flags=re.I)
    return ' '.join(re.findall(r'[a-z]+', label.casefold()))


def statement_types(rows):
    labels = [words(row['label']) for row in rows]
    clean = set(labels)
    types = set()
    if ('total assets' in clean and any('total liabilities and' in row or 'total equity' in row
                                        or 'total stockholders equity' in row for row in labels)):
        types.add('balance_sheet')
    if all(any(f'{activity} activities' in row for row in labels)
           for activity in ('operating', 'investing', 'financing')):
        types.add('cash_flows')
    if (any('net income' in row or 'net earnings' in row for row in labels)
            and any('income tax' in row or 'earnings per share' in row for row in labels)
            and any(row in {'operating income', 'operating profit', 'net interest income', 'total revenue',
                            'net operating revenues', 'net sales', 'total net revenue',
                            'total revenues', 'revenues', 'revenue'} for row in labels)):
        types.add('income_statement')
    return types


def row_meaning(metric, concept, label, statements):
    row = words(label)
    required = 'balance_sheet' if metric in ('assets', 'liabilities', 'deposits') else (
        'cash_flows' if metric == 'operating_cash_flow' else 'income_statement')
    if required not in statements:
        return None
    if metric == 'revenue':
        if row in ('net sales', 'sales net'):
            basis, presentation = 'net_sales', '销售净额'
        elif row in ('net operating revenue', 'net operating revenues'):
            basis, presentation = 'net_operating_revenue', '营业收入净额'
        elif row in ('revenue', 'revenues', 'total revenue', 'total revenues', 'net revenue', 'net revenues',
                     'operating revenue', 'operating revenues'):
            basis, presentation = 'reported_revenue', '营业收入'
        else:
            return None
        tax, qualifier = {
            'RevenueFromContractWithCustomerExcludingAssessedTax': ('tax_excluded', '不含代收税'),
            'RevenueFromContractWithCustomerIncludingAssessedTax': ('tax_included', '含适用代收税'),
        }.get(concept, ('report_basis', '报表口径'))
        return basis + ':' + tax, f'{presentation}（{qualifier}）', required
    if metric == 'net_income':
        if concept == 'NetIncomeLoss' and (
                row in ('net income', 'net earnings', 'net loss', 'net income loss')
                or re.match(r'net (income|earnings|loss)( loss)? attributable to (shareowners|shareholders|stockholders|the parent|the company)', row)):
            return 'profit_parent', '归属于母公司股东的净利润', required
        if concept == 'ProfitLoss' and row in (
                'net income', 'net loss', 'net income loss', 'consolidated net income', 'consolidated net loss',
                'consolidated net income loss', 'net income before noncontrolling interests'):
            return 'profit_consolidated', '合并净利润（含非控股权益）', required
        return None
    accepted = {
        'operating_income': ('operating income', 'operating profit', 'income from operations',
                             'operating loss', 'operating income loss', 'income loss from operations'),
        'assets': ('total assets',),
        'liabilities': ('total liabilities',),
        'deposits': ('deposits', 'total deposits'),
        'net_interest': ('net interest income', 'net interest expense', 'net interest income expense'),
        'noninterest': ('noninterest income', 'noninterest revenue', 'non interest income', 'non interest revenue',
                        'total noninterest income', 'total noninterest revenue'),
        'credit_provision': ('provision for credit losses', 'provision for loan and lease losses',
                             'provision for loan lease and other losses'),
        'interest_income': ('interest income', 'total interest income', 'interest and dividend income',
                            'total interest and dividend income'),
    }
    if metric == 'operating_cash_flow':
        if not row.startswith('net cash') or not row.endswith('operating activities'):
            return None
    elif metric == 'deposits' and re.fullmatch(r'deposits\s*\(included [^)]{1,160} at fair value\)', label, re.I):
        return 'deposits', None, required
    elif row not in accepted.get(metric, ()):
        return None
    if metric == 'interest_income' and 'dividend' in row:
        return 'interest_and_dividend_income', '利息及股息收入', required
    return metric, None, required


def semantic_description(semantic, default):
    if semantic == 'profit_parent':
        return '这是归属于母公司股东的本期利润。'
    if semantic == 'profit_consolidated':
        return '这是合并主体的本期利润，包含非控股权益。'
    if semantic == 'reported_revenue:tax_excluded':
        return '收入按原文及标签列示，已排除代收税款。'
    if semantic.endswith(':tax_included'):
        return '按原文及标签列示的收入包含适用代收税款。'
    return default
