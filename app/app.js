'use strict';

const $ = id => document.getElementById(id);
function el(tag, className = '', value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

const sections = ['overview', 'financials', 'announcements', 'reporting'];
const initial = new URL(location.href).searchParams;
const currencyNames = {USD: '美元', TWD: '新台币'};
let section = sections.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
let cik = '', model = null, loadID = 0, searchID = 0;
let currentIssuer = null, selectedTicker = null, researchInfo = null, reportList = [], lastAttempt = null;
const sourceStatuses = {
  network_disabled: 'SEC 网络访问未开启', authorization_blocked: 'SEC 拒绝访问，本轮已停止',
  rate_limited: 'SEC 限流，本轮已停止', fetch_failed: 'SEC 请求失败',
  wrong_mime: 'SEC 返回了不支持的格式', error_document: 'SEC 返回了错误页面',
  no_periodic_filing_in_window: '时间窗内未找到定期报告',
  source_validation_failed: 'SEC 目录资料未通过校验',
  unsupported_filing_form: '该表单已找到，自动财务提取暂未支持',
  partial_history_latest_unproven: '历史目录存在缺口，无法确认最新报告',
  evidence_rejected: '原文或数据核验未通过', source_unavailable: 'SEC 来源暂不可用',
};
const factStatuses = {
  no_candidate: '未找到适用的标准标签', missing_same_filing_companyfacts: '同份申报的结构化旁证缺失',
  ambiguous_concept_or_period: '标签或期间不唯一', unsupported_original_number: '原文数字格式暂不支持',
  conflicting_original_values: '原文候选数值冲突', companyfacts_mismatch: '原文与结构化旁证不一致',
};

function sourceLink(text, source, cikValue, accession) {
  const url = new URL(source.source_url || source.original_url || source.url);
  const prefix = '/Archives/edgar/data/' + Number(cikValue) + '/' + accession.replaceAll('-', '') + '/';
  const filename = url.pathname.slice(prefix.length);
  if (url.origin !== 'https://www.sec.gov' || !url.pathname.startsWith(prefix) ||
      !/^[A-Za-z0-9][A-Za-z0-9_.-]*\.html?$/.test(filename) || filename.includes('..') ||
      url.username || url.password || url.search || url.hash) throw Error('invalid evidence URL');
  if (source.anchor) {
    if (!/^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,159}$/.test(source.anchor)) throw Error('invalid evidence anchor');
    url.hash = source.anchor;
  }
  const node = el('a', '', text);
  node.href = url.href;
  node.target = '_blank';
  node.rel = 'noopener noreferrer';
  return node;
}

function showSection(next, focus = false) {
  section = sections.includes(next) ? next : 'overview';
  for (const name of sections) {
    const available = model || (name === 'announcements' && researchInfo?.announcements)
      || (name === 'reporting' && currentIssuer);
    $(name).hidden = !available || name !== section;
  }
  $('error').hidden = !lastAttempt || !['overview', 'financials'].includes(section);
  for (const button of document.querySelectorAll('[data-section]')) {
    if (button.dataset.section === section) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  const url = new URL(location.href);
  url.hash = section;
  if (model) {
    url.searchParams.set('cik', model.issuer.cik);
    url.searchParams.set('report', model.document.accession);
  }
  history.replaceState(null, '', url);
  if (focus && model) {
    const heading = $(section).querySelector('h2');
    heading.tabIndex = -1;
    heading.focus({preventScroll: true});
  }
}

document.querySelectorAll('[data-section]').forEach(button => {
  button.addEventListener('click', () => showSection(button.dataset.section, true));
});
window.addEventListener('hashchange', () => {
  if (sections.includes(location.hash.slice(1))) showSection(location.hash.slice(1));
});

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('theme').textContent = theme === 'dark' ? '白天' : '夜间';
  $('theme').setAttribute('aria-label', theme === 'dark' ? '切换到白天模式' : '切换到夜间模式');
  try { localStorage.setItem('hiwd-company-theme', theme); } catch (_) {}
}
let preference;
try { preference = localStorage.getItem('hiwd-company-theme'); } catch (_) {}
setTheme(preference || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
$('theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

async function request(path, params, body = null) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const suffix = body ? '' : '?' + new URLSearchParams(params);
    const settings = {cache: 'no-store', signal: controller.signal};
    if (body) {
      settings.method = 'POST';
      settings.headers = {'Content-Type': 'application/json'};
      settings.body = JSON.stringify(body);
    }
    const response = await fetch(path + suffix, settings);
    const payload = await response.json();
    if (!response.ok) throw Error(payload.status || 'fetch_failed');
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

function beginLoad() {
  model = null;
  lastAttempt = null;
  $('error').hidden = true;
  $('error-source').replaceChildren();
  $('loading').hidden = false;
  for (const name of sections) $(name).hidden = true;
  return ++loadID;
}

function displayError(error) {
  const messages = {
    evidence_validation_failed: '财报证据校验失败，数字已隐藏。',
    not_found: '本地快照里未找到这份报告。',
    unsupported: '当前目录或财报格式暂未支持。',
    report_not_verified: '报告已发现，财务数字尚未通过核验。',
    ...sourceStatuses,
  };
  lastAttempt = error;
  $('error-description').textContent = messages[error.message] || '读取财报失败，请重试。';
  $('snapshot-label').textContent = '财务数字待核验';
  const target = reportList.find(report => report.accession === $('report').value);
  if (target?.original_url) $('error-source').append(sourceLink('打开 SEC 官方原文', target, cik, target.accession));
  showSection(section);
}

function displaySecurities(issuer) {
  const security = issuer.securities.find(stock => stock.ticker === selectedTicker) || issuer.securities[0];
  const format = stock => stock.ticker + ' · ' + stock.exchange + ' · ' + stock.type +
    (stock.underlying_shares ? '（每份代表 ' + stock.underlying_shares + ' 股普通股）' : '');
  $('company-intro').textContent = security ? format(security) : 'SEC 发行人';
  const other = $('other-securities');
  const extras = issuer.securities.filter(stock => stock !== security);
  other.open = false;
  other.hidden = !extras.length;
  other.querySelector('summary').textContent = '其他挂牌证券（' + extras.length + '）';
  other.querySelector('ul').replaceChildren(...extras.map(stock => el('li', '', format(stock))));
}

function selectIssuer(issuer, accession, official = false) {
  cik = issuer.cik;
  currentIssuer = issuer;
  selectedTicker = issuer.matched_tickers?.[0] || null;
  researchInfo = null;
  reportList = [];
  $('company-title').textContent = issuer.label;
  $('company-meta').textContent = '发行人 · CIK ' + cik;
  displaySecurities(issuer);
  $('search-results').hidden = true;
  $('research-state').textContent = '';
  $('research-action').hidden = !official;
  $('report').replaceChildren(el('option', '', '正在查找报告'));
  $('report').disabled = true;
  if (official) startResearch(accession);
  else loadReports(accession);
}

async function findCompanies(event) {
  event.preventDefault();
  const query = $('company-query').value.trim();
  const lookupID = ++searchID;
  const list = $('search-results');
  list.hidden = true;
  list.replaceChildren();
  if (!query) {
    $('search-status').textContent = '请输入公司代码或名称。';
    return;
  }
  $('search-status').textContent = '正在查找发行人…';
  try {
    const data = await request('/api/search', {q: query});
    if (lookupID !== searchID) return;
    $('directory-status').textContent = data.directory
      ? ('SEC 目录 · ' + data.directory.date + (data.directory.cache === 'stale' ? ' · 缓存已过期' : ''))
      : '当前只查询可用的本地审阅样本。';
    if (!data.candidates.length) {
      $('search-status').textContent = data.status === 'source_unavailable'
        ? (sourceStatuses[data.reason] || 'SEC 目录暂不可用。')
        : '当前可用的发行人目录未匹配此查询。';
      return;
    }
    $('search-status').textContent = '找到 ' + data.candidates.length + ' 个发行人。请选择一项。';
    for (const issuer of data.candidates) {
      const item = el('li'), button = el('button', 'candidate', issuer.name);
      button.type = 'button';
      button.append(el('small', '', issuer.securities.map(s => s.ticker + ' · ' + s.exchange + ' · ' + s.type).join(' / ')));
      button.addEventListener('click', () => {
        $('company-query').value = issuer.matched_tickers[0] || issuer.securities[0].ticker;
        $('search-status').textContent = '';
        selectIssuer(issuer, null, data.scope === 'sec_directory');
        $('company-title').tabIndex = -1;
        $('company-title').focus({preventScroll: true});
      });
      item.append(button);
      list.append(item);
    }
    list.hidden = false;
    list.querySelector('button')?.focus();
  } catch (_) {
    if (lookupID === searchID) $('search-status').textContent = '公司搜索暂时不可用，请重试。';
  }
}
$('search-form').addEventListener('submit', findCompanies);
$('search-results').addEventListener('keydown', event => {
  const buttons = [...$('search-results').querySelectorAll('button')];
  if (!buttons.length) return;
  const index = buttons.indexOf(document.activeElement);
  if (event.key === 'Escape') {
    $('search-results').hidden = true;
    $('company-query').focus();
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
  }
});

function refreshReportOptions(reports, accession) {
  reportList = reports;
  const select = $('report');
  select.replaceChildren(...reports.map(entry => {
    const status = entry.status === 'discovered' ? ' · 待提取' : '';
    const option = el('option', '', entry.form + ' · ' + entry.label + status);
    option.value = entry.accession;
    return option;
  }));
  if (!reports.length) select.append(el('option', '', '当前没有可选报告'));
  select.disabled = !reports.length;
  if (accession && reports.some(row => row.accession === accession)) select.value = accession;
}

async function loadReports(accession) {
  const id = beginLoad();
  try {
    const list = await request('/api/reports', {cik});
    if (id !== loadID) return;
    refreshReportOptions(list.reports, accession);
    if (!list.reports.length) throw Error('not_found');
    const data = await request('/api/reader', {cik, unit: $('unit').value, ...(accession ? {accession} : {})});
    if (id !== loadID) return;
    $('report').value = data.document.accession;
    render(data);
  } catch (error) {
    if (id === loadID) displayError(error);
  } finally {
    if (id === loadID) $('loading').hidden = true;
  }
}

function researchSummary(info) {
  if (!info) return;
  const freshness = info.freshness === 'stale' ? '缓存已过期' : 'SEC 目录';
  const gap = info.history_window?.complete ? '' : ' · 历史窗部分可核验';
  const fallback = info.index_refresh_status ? ' · ' + (sourceStatuses[info.index_refresh_status] || '更新失败') : '';
  $('research-state').textContent = '来源截至 ' + info.source_cutoff + '（美东） · ' + freshness + gap + fallback;
}

async function waitForResearch(cikValue, accession, id) {
  let result = await request('/api/research', {}, {cik: cikValue, ...(accession ? {accession} : {})});
  for (let checks = 0; result.status === 'pending' && checks < 150 && id === loadID; checks++) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    if (id === loadID) result = await request('/api/research', {cik: cikValue});
  }
  return result;
}

async function startResearch(accession) {
  const id = beginLoad(), target = cik;
  $('research-action').disabled = true;
  $('research-state').textContent = '正在核对 SEC 申报目录和原文…';
  try {
    let result = await waitForResearch(target, accession, id);
    if (id !== loadID) return;
    if (result.status === 'failed' || !result.history) {
      if (result.cached) {
        researchInfo = result.cached;
        const list = await request('/api/reports', {cik: target});
        if (id !== loadID) return;
        refreshReportOptions(list.reports, accession ?? researchInfo.latest_accession);
        renderAnnouncements();
      }
      const explanation = result.status === 'busy' ? '已有研究任务在运行，请稍后重试。' :
        (sourceStatuses[result.reason] || '暂时无法完成 SEC 核验。');
      $('research-state').textContent = explanation;
      throw Error(result.reason || 'source_unavailable');
    }
    researchInfo = result;
    researchSummary(result);
    const desired = accession || result.latest_accession;
    const list = await request('/api/reports', {cik: target});
    if (id !== loadID) return;
    refreshReportOptions(list.reports, desired);
    renderAnnouncements();
    if (!desired || (desired === result.selected_accession && result.verification === 'evidence_rejected'))
      throw Error(result.verification);
    if (!result.fetched_accessions.includes(desired)) throw Error(result.verification === 'source_unavailable'
      ? (result.diagnostic || result.verification) : result.verification);
    const data = await request('/api/reader', {cik: target, accession: desired, unit: $('unit').value});
    if (id === loadID) render(data);
  } catch (error) {
    if (id === loadID) displayError(error);
  } finally {
    if (id === loadID) {
      $('loading').hidden = true;
      $('research-action').disabled = false;
    }
  }
}

function appendNarrative(target, kind, label, evidence, link) {
  const entry = evidence.find(item => item.kind === kind);
  if (entry) target.replaceChildren(el('p', '', entry.text), link(label, entry));
  else target.replaceChildren(el('p', 'minor', '该报告的相关内容尚未核验。'));
}

function render(data) {
  if (!['real_official_reviewed_snapshot', 'real_official_auto_verified'].includes(data.dataset_kind))
    throw Error('evidence_validation_failed');
  const {document: doc, issuer} = data;
  const link = (label, source) => sourceLink(label, source, issuer.cik, doc.accession);
  $('company-title').textContent = issuer.label;
  $('company-meta').textContent = '发行人 · CIK ' + issuer.cik;
  displaySecurities(issuer);
  $('summary-period').textContent = doc.form + ' · ' + doc.report_end;
  const mode = data.acquisition_mode === 'sec_on_demand' ? 'SEC 按需核验' :
    data.acquisition_mode === 'manual_import' ? '人工导入原文' : 'SEC 官方快照';
  $('snapshot-label').textContent = mode + ' · ' + (data.rows.length ? '已核验' : '仅原文');
  $('provenance-mode').textContent = mode + ' · 核验日 ' + doc.reviewed_on + ' · 本地读取';
  const unit = $('unit');
  unit.options[0].textContent = '亿' + currencyNames[data.currency];
  unit.options[1].textContent = '百万' + currencyNames[data.currency];
  unit.disabled = !data.rows.length;
  if (issuer.industry && !data.narrative.some(item => item.kind === 'business')) {
    $('business').replaceChildren(el('p', '', 'SEC 行业分类 · ' + issuer.industry));
  } else {
    appendNarrative($('business'), 'business', '报告中的业务说明', data.narrative, link);
  }
  $('management').replaceChildren(el('p', 'minor', '管理层归因待原文语义核验。'));
  const components = $('composition');
  components.replaceChildren();
  for (const item of data.segments) {
    const node = el('li');
    node.append(el('span', '', item.name), el('strong', '', item.amount + ' ' + data.unit), link('原文', item.fact));
    components.append(node);
  }
  if (!data.segments.length) components.append(el('li', 'minor', '该报告的收入构成尚未核验。'));

  $('source-summary').replaceChildren(el('h3', '', '报告来源'),
    el('p', '', 'CIK ' + issuer.cik + ' · ' + data.accounting_label),
    el('p', '', doc.form + ' · 申报日 ' + doc.published_on), link('打开 SEC 官方原文', doc),
    el('p', 'source-hash', '文档版本 ' + doc.accession));
  $('report-context').replaceChildren(el('p', '', '报告期末 ' + doc.report_end + ' · ' + data.currency + ' · ' + data.accounting_label),
    el('p', '', '每项数字保留原文锚点、XBRL 期间、币种、倍率和版本。比较期使用同一份报告所列的数据。'));
  $('facts-caption').textContent = data.rows.length + ' 项指标 · ' + data.unit + ' · ' + data.accounting_label;
  $('financial-table').hidden = !data.rows.length;
  $('financial-empty').hidden = !!data.rows.length;
  $('financial-empty').textContent = doc.attachments?.length
    ? '已核验官方披露与附件。附件财务数字尚未结构化。'
    : '报告原文已找到，当前没有通过核验的财务数字。';
  const gaps = $('financial-gaps');
  const missing = data.metric_outcomes.filter(item => item.status !== 'verified');
  gaps.replaceChildren(...missing.map(item => el('li', '', item.label + ' · ' +
    (factStatuses[item.status] || '尚未核验'))));
  gaps.hidden = !missing.length;
  const filing = el('div', 'filing'), filingText = el('div');
  filingText.append(el('h3', '', doc.form + ' · ' + (doc.label || doc.report_end)), el('p', '', '申报日 ' + doc.published_on));
  filing.append(filingText, link('查看官方原文', doc));
  const disclosures = $('filing-record');
  disclosures.replaceChildren(filing);
  for (const attachment of doc.attachments || []) {
    const node = el('p', 'attachment');
    node.append(link(attachment.label, attachment));
    disclosures.append(node);
  }
  if (researchInfo) renderAnnouncements();
  else $('announcement-state').textContent = data.sections.announcements.label;
  $('media-state').textContent = data.sections.reporting.label;
  renderRows(data, link);
  model = data;
  showSection(section);
}

function renderRows(data, link) {
  const explanations = $('explanations'), keys = $('key-facts'), table = $('facts-table');
  explanations.replaceChildren();
  keys.replaceChildren();
  table.replaceChildren();
  for (const [index, row] of data.rows.entries()) {
    const claim = data.claims[index], fact = row.current;
    const explanation = el('section', 'explanation'), trace = el('div', 'claim-source');
    trace.append(link('本期原文', fact));
    if (row.prior) trace.append(link('比较期原文', row.prior));
    explanation.append(el('h4', '', row.label), el('p', '', claim.text), trace);
    explanations.append(explanation);

    const key = el('div', 'key-fact'), top = el('div', 'key-fact-top'), bottom = el('div', 'fact-bottom');
    top.append(el('span', 'fact-label', row.label), el('span', 'fact-value', row.current_display));
    const inspect = el('a', '', '查看证据');
    inspect.href = '#financials';
    inspect.addEventListener('click', event => {
      event.preventDefault();
      showSection('financials');
      const tr = $('row-' + row.metric);
      tr.classList.add('is-focused');
      tr.tabIndex = -1;
      tr.focus({preventScroll: true});
      tr.scrollIntoView({block: 'center'});
    });
    bottom.append(el('span', '', data.unit + ' · ' + row.period_label), inspect);
    key.append(top, bottom);
    keys.append(key);

    const tr = el('tr');
    tr.id = 'row-' + row.metric;
    const title = el('th', '', row.label);
    title.scope = 'row';
    title.append(el('small', '', row.period_label));
    const now = el('td', '', row.current_display), prior = el('td', '', row.prior_display ?? '待核验');
    now.append(el('small', '', fact.period_end));
    if (row.prior) prior.append(el('small', '', row.prior.period_end));
    const reference = el('td');
    reference.append(link('本期原文', fact), el('small', '', row.statement));
    if (row.prior) reference.append(link('比较期原文', row.prior));
    tr.append(title, now, prior, el('td', '', row.yoy ? row.yoy.value + '%' : '暂不计算'), reference);
    table.append(tr);
  }
  const revenue = data.rows.find(row => row.metric === 'revenue'), detail = $('calculation-detail');
  detail.replaceChildren();
  if (revenue?.yoy) {
    detail.append(el('p', 'calculation-line',
      '收入同比 =（' + revenue.current.value + ' ÷ ' + revenue.prior.value + ' − 1）× 100 = ' +
      revenue.yoy.value + '%。输入为基础' + currencyNames[data.currency] + '，保留两位小数。'));
  }
}

function renderAnnouncements() {
  const current = researchInfo?.announcements;
  if (!current) return;
  const state = current.state === 'observed' ? 'SEC 目录覆盖此窗口' : '覆盖不完整';
  $('announcement-state').textContent = current.start + ' 至 ' + current.end + '（美东申报日） · ' + state;
  const list = $('filing-record');
  list.replaceChildren();
  if (!current.entries.length) {
    list.append(el('p', 'minor', current.state === 'observed'
      ? '此次目录观察范围内未找到 8-K 或 6-K。' : '当前可读目录中未找到公告，覆盖仍待核验。'));
    return;
  }
  for (const entry of current.entries) {
    const card = el('article', 'filing'), copy = el('div');
    const codes = entry.items.filter(item => item.code !== '9.01');
    const title = codes[0]?.label || (entry.form.startsWith('6-K') ? '外国私人发行人报告' : '当前报告');
    const codeText = entry.items.map(item => item.code + ' ' + item.label).join(' · ');
    copy.append(el('h3', '', title + (entry.is_amendment ? ' · 修订' : '')),
      el('p', 'filing-meta', entry.form + ' · ' + entry.published_on),
      el('p', '', codeText ? 'SEC 事项分类：' + codeText : entry.summary));
    card.append(copy, sourceLink('查看 SEC 原文', entry, cik, entry.accession));
    list.append(card);
  }
}

async function readSelected() {
  if ($('report').disabled) return cik ? startResearch() : initialize();
  const accession = $('report').value;
  const report = reportList.find(item => item.accession === accession);
  if (report?.status === 'discovered') return startResearch(accession);
  const id = beginLoad();
  try {
    const data = await request('/api/reader', {cik, accession, unit: $('unit').value});
    if (id === loadID) render(data);
  } catch (error) {
    if (id === loadID) displayError(error);
  } finally {
    if (id === loadID) $('loading').hidden = true;
  }
}
$('report').addEventListener('change', readSelected);
$('unit').addEventListener('change', readSelected);
$('retry').addEventListener('click', readSelected);
$('research-action').addEventListener('click', () => startResearch());

async function initialize() {
  try {
    const initialCik = initial.get('cik');
    if (initialCik) {
      const saved = await request('/api/research', {cik: initialCik});
      if (!cik && saved.issuer) {
        selectIssuer(saved.issuer, initial.get('report'), false);
        researchInfo = saved;
        $('research-action').hidden = false;
        researchSummary(saved);
        renderAnnouncements();
        return;
      }
    }
    const params = initialCik ? {cik: initialCik} : {};
    const data = await request('/api/reader', params);
    if (!cik) selectIssuer(data.issuer, initial.get('report'));
  } catch (error) {
    if (cik) return;
    $('loading').hidden = true;
    $('company-query').focus();
    displayError(error);
  }
}
initialize();
