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
  for (const name of sections) $(name).hidden = !model || name !== section;
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

async function request(path, params) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path + '?' + new URLSearchParams(params), {cache: 'no-store', signal: controller.signal});
    const body = await response.json();
    if (!response.ok) throw Error(body.status || 'fetch_failed');
    return body;
  } finally {
    clearTimeout(timeout);
  }
}

function beginLoad() {
  model = null;
  $('error').hidden = true;
  $('loading').hidden = false;
  for (const name of sections) $(name).hidden = true;
  return ++loadID;
}

function displayError(error) {
  const messages = {
    evidence_validation_failed: '财报证据校验失败，数字已隐藏。',
    not_found: '本地快照里未找到这份报告。',
    unsupported: '本原型暂未覆盖这个发行人。',
  };
  $('error-description').textContent = messages[error.message] || '读取本地财报失败，请重试。';
  $('snapshot-label').textContent = '财报不可用';
  $('error').hidden = false;
}

function selectIssuer(issuer, accession) {
  cik = issuer.cik;
  $('company-title').textContent = issuer.label;
  $('company-meta').textContent = issuer.name;
  $('company-intro').textContent = '正在读取已核验报告';
  $('search-results').hidden = true;
  loadReports(accession);
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
    if (data.status === 'unsupported') {
      $('search-status').textContent = '本原型暂未覆盖这个查询。支持 AAPL、MSFT、NVDA、TSM。';
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
        selectIssuer(issuer);
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

async function loadReports(accession) {
  const id = beginLoad();
  const report = $('report');
  report.disabled = true;
  report.replaceChildren(el('option', '', '正在读取报告'));
  try {
    const [list, data] = await Promise.all([request('/api/reports', {cik}),
      request('/api/reader', {cik, unit: $('unit').value, ...(accession ? {accession} : {})})]);
    if (id !== loadID) return;
    if (!list.reports.length) throw Error('not_found');
    report.replaceChildren(...list.reports.map(entry => {
      const option = el('option', '', entry.form + ' · ' + entry.label + ' · ' + entry.report_end);
      option.value = entry.accession;
      return option;
    }));
    report.value = data.document.accession;
    report.disabled = false;
    render(data);
  } catch (error) {
    if (id === loadID) displayError(error);
  } finally {
    if (id === loadID) $('loading').hidden = true;
  }
}

function appendNarrative(target, kind, label, evidence, link) {
  const entry = evidence.find(item => item.kind === kind);
  if (entry) target.replaceChildren(el('p', '', entry.text), link(label, entry));
  else target.replaceChildren(el('p', 'minor', '该报告的相关内容尚未核验。'));
}

function render(data) {
  if (data.dataset_kind !== 'real_official_reviewed_snapshot') throw Error('evidence_validation_failed');
  const {document: doc, issuer} = data;
  const link = (label, source) => sourceLink(label, source, issuer.cik, doc.accession);
  const securities = issuer.securities.map(stock => stock.ticker + ' · ' + stock.exchange + ' · ' + stock.type +
    (stock.underlying_shares ? '（每份代表 ' + stock.underlying_shares + ' 股普通股）' : ''));
  $('company-title').textContent = issuer.label;
  $('company-meta').textContent = issuer.name;
  $('company-intro').textContent = securities.join(' / ');
  $('summary-period').textContent = doc.form + ' · ' + doc.report_end;
  const mode = data.acquisition_mode === 'manual_import' ? '人工导入原文' : 'SEC 官方快照';
  $('snapshot-label').textContent = mode + ' · ' + (data.rows.length ? '已核验' : '仅原文');
  $('provenance-mode').textContent = mode + ' · 核验日 ' + doc.reviewed_on + ' · 本地读取';
  const unit = $('unit');
  unit.options[0].textContent = '亿' + currencyNames[data.currency];
  unit.options[1].textContent = '百万' + currencyNames[data.currency];
  unit.disabled = !data.rows.length;
  appendNarrative($('business'), 'business', '报告中的业务说明', data.narrative, link);
  appendNarrative($('management'), 'management_statement', '管理层归因原文', data.narrative, link);
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
  $('financial-empty').textContent = '已核验官方披露与附件。附件财务数字尚未结构化。';
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
  $('announcement-state').textContent = data.sections.announcements.label;
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

async function readSelected() {
  if ($('report').disabled) return cik ? loadReports() : initialize();
  const id = beginLoad();
  try {
    const data = await request('/api/reader', {cik, accession: $('report').value, unit: $('unit').value});
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

async function initialize() {
  try {
    const params = initial.get('cik') ? {cik: initial.get('cik')} : {};
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
