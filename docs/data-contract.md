# 候选数据合约 — Phase 1 设计，尚未实现

本文件是 Issue #1 的方案交付，不表示已经存在数据库/API 或已取得数据许可。

## 身份与文档

| 实体 | 必要字段/约束 |
| --- | --- |
| Issuer | 内部不可变 issuer_id、法定名称、名称别名及语言、注册地；外部标识表保存 scheme/value/valid_from/valid_to/source_evidence。CIK 规范为十位字符串；LEI 等未知可空，不生成假的标识 |
| Security | security_id、issuer_id、market、交易所/MIC、ticker 原样字符串、证券类别、上市/退市有效期、交易币种；唯一键含市场/交易所/有效期，不能单用 ticker |
| SecurityRelation | ADR/ADS 与基础股票、A/H、双柜台关系；ratio、有效期及官方证据。比例未知禁止 EPS 互换；同 issuer 不代表证券完全可互换 |
| SourcePolicy | source_id、精确域名/路径、来源类型、许可 URL/凭证引用、用途/地区/受众、可缓存/可摘要/可传模型、保存期限、quota、审批及复核日期、enabled（默认 false） |
| Document | source_document_id（SEC accession 等）、issuer_id、关联证券、form/type/language；report_start/end、fiscal_year/period、published_at + 原时区 + 精度、accepted_at、first_seen_at、fetched_at；original_url、landing_url、mirror_url 分开；content_hash、MIME、权利引用 |
| DocumentVersion | document_id、version、supersedes、修订/更正关系、抓取状态、有效起点；原版不可覆盖，保留 as-of 查询。相同内容中英文/AH 文件是相关版本，不能单靠标题删掉 |
| Evidence | document_version_id、页码（1 起）、节/表/行、HTML anchor 或 XBRL concept/context/unit、短引文（仅许可范围）、位置指纹；定位失败不可标 verified |

`market` 为 US/HK/CN；`ticker` 的 00700、09988 前导零保留。600519.SH、sh600519、交易所 600519 只是同一 security 的不同供应商表示；用户输入和供应商代码分别存储，不靠全局去前缀映射。`ICBC` 返回 H 股不应无提示替换 A 股，`Apple` 返回 APLE 也不可自动选中。双重上市的报告去重以发行人和原文版本为基础，查询仍保留证券上下文。

## 财务事实与口径

FinancialFact 必须包含：

- issuer_id、document_version_id、concept（原始 taxonomy/tag/扩展标签与规范映射版本）、decimal 原值字符串、原始显示值及精度。
- period_start/end 或 instant，duration/instant，fiscal_year、fiscal_period、单季/累计/全年/TTM；52/53 周财年保留真实日期，不硬改为自然季末。
- 披露币种、单位（货币/股数/每股/比例）、倍率、汇兑是否发生及原币/汇率/日期/方法。缺其中关键语义则不可计算，不由上市地推断。
- accounting_standard（US_GAAP/IFRS/PRC_GAAP/unknown）、GAAP/non-GAAP、合并/母公司/分部/归母口径、审计状态、持续/终止经营、dimensional context。
- 原始申报日期、版本和证据；取哪个版本/哪个期间的选择理由。companyfacts 中多个期间及同一期重述并存，不取数组最后一个就结束。
- quality：unverified/verified/conflict/quarantined；校验规则版本与人工核验时间。没有原文可定位的腾讯财务行只能是 unverified。

发布日精度可以是 date；不补午夜冒充准确时刻。原文明确的“未披露”与搜索未返回、许可拒绝、网络失败必须不同。跨市场准则、财年/季度、币种和合并口径不同，默认不比较。银行无工业企业“收入/毛利”同等定义时显示不适用，不能自动套公式。

## 适配器接口（候选）

```typescript
type Status = 'ok' | 'partial' | 'not_disclosed' | 'not_found'
  | 'unsupported' | 'authorization_blocked' | 'policy_blocked'
  | 'rate_limited' | 'fetch_failed' | 'parse_failed' | 'conflict';

type Result<T> = {
  status: Status;
  records: T[];
  sourceId: string;
  fetchedAt: string;
  policyId: string;
  nextCursor: string | null;
  coverage: { requestedFrom: string | null; requestedTo: string | null;
    observedFrom: string | null; observedTo: string | null;
    complete: boolean; gaps: string[] };
  retryAfter: string | null;
  errors: { code: string; safeMessage: string; retryable: boolean }[];
};

interface DisclosureAdapter {
  // 调用前先检查已审批的 SourcePolicy 与用途，非任意 HTTP 工具。
  capabilities(): Result<Capability>;
  search(query: { text: string; language: string; market: string }): Promise<Result<IdentityCandidate>>;
  resolveSecurity(id: SecurityId): Promise<Result<VerifiedIdentity>>;
  listDocuments(q: { issuerId: string; types: string[]; from: string;
    to: string; cursor: string | null }): Promise<Result<DocumentMetadata>>;
  fetchDocument(id: ApprovedSourceDocumentId): Promise<Result<DocumentVersion>>;
  extractFacts(id: DocumentVersionId): Promise<Result<FinancialFact>>;
}
```

上面类型是接口草案，其引用类型需 Phase 1 实现；不在当前仓库编译或冒称可用 SDK。search 返回候选并保留身份不确定性。`ok` 仅表示所请求操作完整完成；覆盖完整性还要按报告类型/时间窗核验。状态可部分成功并附单条错误；401/403/政策限制不可装成空列表或 `not_disclosed`。

SEC：官方身份 → recent/history files → canonical Archives 原文 → XBRL 定位与版本校验。20-F/6-K 不机械映射成 10-K/10-Q。HK/A 股各走自己的授权适配器及字段映射；腾讯适配器只提供候选线索，镜像不能进入 original_url。媒体另走 NewsAdapter，不能伪装成法定披露。

## 结论和确定性计算

Claim 保存 kind（source_fact/management_statement/ai_explanation）、文字、evidence_ids、fact_ids、comparison_context、计算产物 ID、模型/提示版本、生成和复核时间。所有实质结论至少一条可核验来源；解释没有独立证据时只能解释已有事实，不能扩展出新的数字或因果。

计算计划：以 Decimal 做倍率归一；同比 `(current / prior - 1) × 100` 仅在期间长度、币种、单位、准则、范围和版本可比时执行。基期为零、符号转换导致比率误导或不可比时不输出增长率，改为说明变化。累计转单季只在同一财年和口径的相邻累计期且原文可核对时相减；Q4 差额只能标“计算值”，不是独立披露季报；修订后重新计算并保留旧版。

Calculation 保存公式 ID/version、全部输入 fact/version、decimal 结果、精度/舍入规则和拒绝原因。模型不执行财务算术、不补货币和倍率、不将管理层解释升级为系统因果。财报过期、来源冲突和修订以状态可见；抓取失败使用最后核验数据也必须显示截止日。

## 计划中的验收测试

1. 00700、80700、TCEHY 关联而不混证券；ICBC 英文搜索无 A 股时要求明确市场；APLE 不自动成为 AAPL。
2. TSM ADR 比例/报告币种未知、腾讯港股 CurrencyType 冲突、A 股倍率缺失时拒绝计算；不能静默以 CNY/HKD/USD 补齐。
3. 不同财年/52 周报告、YTD/单季、GAAP/non-GAAP、母公司/合并不能自动同比；更正会生成新文档版本及新计算。
4. 403、429、超时、HTTP 200 HTML 错误页、分页不完整与来源明确未披露分别返回状态，不污染成功缓存。
5. 恶意文档提示、跨域重定向、内网地址、DNS rebinding、超大压缩包、脚本/宏无法获取网络或密钥。
6. 每项结论的原文 URL 和位置可复核；失效链接、语言变体、修订与数据过期不会被隐藏。

这些是下一阶段验收条件，**本阶段仅测试了探针诊断及其拒绝策略，尚未实现生产数据管道**。
