'use strict';
const $ = id => document.getElementById(id);
const el = (tag, className, text) => { const node = document.createElement(tag); if(className) node.className=className; if(text!==undefined) node.textContent=text; return node; };
const sections=['overview','financials','announcements','reporting'];
let model=null, section=sections.includes(location.hash.slice(1))?location.hash.slice(1):'overview', requestNumber=0;
function sourceLink(text, fact, anchor=true) {
  const node=el('a','',text), url=new URL(fact.source_url || fact.original_url);
  if(url.origin!=='https://www.sec.gov' || !/^\/Archives\/edgar\/data\/320193\/\d{18}\/[a-z0-9.-]+\.htm$/.test(url.pathname) || url.search || url.hash || url.username) throw Error('Unapproved evidence URL');
  if(anchor) { if(!/^f-\d+$/.test(fact.anchor)) throw Error('Missing evidence anchor'); url.hash=fact.anchor; }
  node.href=url.href; node.target='_blank'; node.rel='noopener noreferrer'; return node;
}
function showSection(next, focus=false) {
  section=sections.includes(next)?next:'overview';
  for(const name of sections) $(name).hidden=!model || name!==section;
  for(const button of document.querySelectorAll('[data-section]')) {
    if(button.dataset.section===section) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  }
  history.replaceState(null,'','#'+section);
  if(focus && model) { const heading=$(section).querySelector('h2'); heading.tabIndex=-1; heading.focus({preventScroll:true}); }
}
document.querySelectorAll('[data-section]').forEach(button=>button.addEventListener('click',()=>showSection(button.dataset.section,true)));
window.addEventListener('hashchange', () => {
  const next = location.hash.slice(1);
  if (sections.includes(next)) showSection(next);
});
function setTheme(theme) {
  document.documentElement.dataset.theme=theme;
  $('theme').textContent=theme==='dark'?'白天':'夜间'; $('theme').setAttribute('aria-label',theme==='dark'?'切换到白天模式':'切换到夜间模式');
  try { localStorage.setItem('hiwd-company-theme',theme); } catch(_) { /* Only preference; no financial data is stored. */ }
}
let preferred; try { preferred=localStorage.getItem('hiwd-company-theme'); } catch(_) {}
setTheme(preferred || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
$('theme').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
function render(data) {
  if(data.dataset_kind!=='real_official_reviewed_snapshot' || data.rows.length!==6) throw Error('Invalid evidence snapshot');
  model=data;
  $('report-period').textContent='2026 财年 · 截至 '+data.document.report_end+' · 10-K';
  const mode=data.acquisition_mode==='manual_import'?'人工导入原文 · 非实时':'SEC 单次取得 · 本地快照';
  $('snapshot-label').textContent=mode;
  $('provenance-mode').textContent=mode+'。核验日期 '+data.document.reviewed_on+'；不代表持续自动更新服务已通过。';
  const explanations=$('explanations'); explanations.replaceChildren();
  const keys=$('key-facts'); keys.replaceChildren();
  const table=$('facts-table'); table.replaceChildren();
  for(let i=0;i<data.rows.length;i++) {
    const row=data.rows[i], claim=data.claims[i], fact=row.current;
    const block=el('section','explanation'); block.append(el('h3','',row.label),el('p','',claim.text));
    const trace=el('div','claim-source');
    const links=el('span','claim-links');
    links.append(sourceLink('本期原文',fact), sourceLink('比较期原文',row.prior));
    trace.append(el('span','','模板解释'),links);
    block.append(trace);
    explanations.append(block);
    const key=el('div','key-fact'), top=el('div','key-fact-top'), bottom=el('div','fact-bottom');
    top.append(el('span','fact-label',row.label),el('span','fact-value',row.current_display));
    bottom.append(el('span','',data.unit+(fact.period_kind==='instant'?' · 期末':' · 全年')));
    const inspect=el('a','','查看证据'); inspect.href='#financials'; inspect.addEventListener('click',event=>{event.preventDefault();showSection('financials');const tr=$('row-'+row.metric);tr.classList.add('is-focused');tr.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});tr.tabIndex=-1;tr.focus({preventScroll:true});});bottom.append(inspect);key.append(top,bottom);keys.append(key);
    const tr=el('tr','');tr.id='row-'+row.metric;
    const title=el('th','',row.label);title.scope='row';title.append(el('small','',fact.period_kind==='instant'?'期末余额':'全年累计'));
    const growth=row.yoy?((row.yoy.value.startsWith('-')?'':'+')+row.yoy.value+'%'):'不计算';
    const original=el('td','');
    original.append(sourceLink('本期原文',fact),el('small','',fact.statement),sourceLink('比较期原文',row.prior));
    tr.append(title,el('td','',row.current_display),el('td','',row.prior_display),el('td','',growth),original);table.append(tr);
  }
  const source=$('source-summary');source.replaceChildren(el('h3','','一份正式年报'),el('p','','Apple Inc. · CIK '+data.issuer.cik),el('p','','发布日 '+data.document.published_on+' · US GAAP · 合并口径'),el('p','','已对照原文 iXBRL 与 SEC XBRL，同一 accession。'));
  source.append(sourceLink('打开 SEC 官方 10-K',data.document,false),el('p','source-hash','文档版本 '+data.document.accession));
  $('facts-caption').textContent='6 项已核验事实 · '+data.unit+' · US GAAP 合并口径';
  const revenue=data.rows[0], detail=$('calculation-detail');detail.replaceChildren();
  const formula = revenue.yoy
    ? '收入同比 = ('+revenue.current.value+' ÷ '+revenue.prior.value+' − 1) × 100 = '+revenue.yoy.value+'%。输入为原始美元值，采用四舍五入。'
    : '本期收入同比未计算，比较口径检查未通过。';
  detail.append(el('p','calculation-line',formula));
  const context=$('report-context');context.replaceChildren();
  ['本期全年：2025-09-28 至 2026-09-26；比较期全年：2024-09-29 至 2025-09-27，均为 52 周。',
   '资产与负债为 2026-09-26 和 2025-09-27 的期末余额，不是全年流量。',
   '原文报表金额单位为百万美元，iXBRL scale=6；先还原基础美元，再确定性换算显示单位。',
   '比较期为本份 2026 年报列示的数字；当前未完成其他财报及历史修订追踪。',
   '每项数字保留原文 anchor、XBRL context、concept、日期和版本。'].forEach(text=>context.append(el('p','',text)));
  const filing=el('div','filing'), filingText=el('div','');filingText.append(el('h3','','Apple 2026 财年 10-K'),el('p','',data.document.published_on+' 发布 · 报告期末 '+data.document.report_end));filing.append(filingText,sourceLink('查看官方原文',data.document,false));$('filing-record').replaceChildren(filing);
  showSection(section);
}
async function load() {
  const id=++requestNumber, controller=new AbortController(), timer=setTimeout(()=>controller.abort(),8000);
  $('error').hidden=true;$('loading').hidden=false;sections.forEach(name=>$(name).hidden=true);
  try {
    const response=await fetch('/api/reader?unit='+encodeURIComponent($('unit').value),{cache:'no-store',signal:controller.signal});
    if(!response.ok) throw Error('Evidence unavailable');
    const data=await response.json();if(id!==requestNumber)return;render(data);
  } catch(_) {
    if(id!==requestNumber)return;model=null;sections.forEach(name=>$(name).hidden=true);$('error').hidden=false;
    $('snapshot-label').textContent='本地获取失败';$('provenance-mode').textContent='证据快照读取失败，当前没有把缺失显示为“未披露”。';
  } finally {clearTimeout(timer);if(id===requestNumber)$('loading').hidden=true;}
}
$('retry').addEventListener('click',load);$('unit').addEventListener('change',load);load();
