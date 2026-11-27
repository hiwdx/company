# hiwd company · Apple 财报阅读原型

这是 PR #4 的历史实验记录。当前运行、导入和多公司核验说明见 [Phase 1B](phase-1b.md)。

[Issue #3](https://github.com/hiwdx/company/issues/3) 的真实数据阅读验收材料。核验日为 2026-11-27（Asia/Shanghai）。基于 `main` 独立开发，未合并的 Phase 0 PR #2 另行补充品牌/UI 研究。

## 来源与接入结果

Apple Inc. 普通股 AAPL，Nasdaq，CIK `0000320193`。本次读取的是 2026 财年正式 Form 10-K，accession `0000320193-26-000026`，申报日 2026-11-03，报告期末 2026-09-26。Apple 投资者关系目录也列出同一正式年报。 [Apple 官方目录](https://investor.apple.com/sec-filings/sec-filings-details/default.aspx?FilingId=19895604) · [SEC 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm)

Phase 0 记录过 SEC 403。Phase 1 在本机使用真实项目和经授权联系信息，按官方规则低频分别请求 submissions、原文及 companyfacts，三项均为 HTTP 200。请求时间、MIME、字节数和内容哈希已留档，联系信息省略。前后响应不同的原因未经 SEC 确认。 [身份与目录请求](evidence/sec-contact-check.json) · [原文与事实请求](evidence/sec-document-check.json) · [SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [访问规则](https://www.sec.gov/about/webmaster-frequently-asked-questions)

这次请求构成单次官方链路成功样本。持续自动接入和生产访问仍待验收。原型运行时只读取本机 SQLite，既不向 SEC 发网络请求，也不启动其他供应商任务。人工导入使用同一批已合法取得的本地文件，也完成现场测试，界面以独立模式标记。留档只有精选事实、引用和校验元数据。

## 原文核对

以下金额为原表中的整数，单位均为**百万美元**。iXBRL 以 scale `6` 转为基础美元。SEC companyfacts 在相同 accession、表单、申报日、期间和币种下的值与原文锚点一致。采用美国公认会计准则与合并口径。表中 FY2025 列为同一份 FY2026 10-K 中的比较期，属于同一文档版本。

| 指标 | 原表与期间 | FY2026 原值 | FY2025 比较期原值 | 同比 | 原文定位 |
| --- | --- | ---: | ---: | ---: | --- |
| 收入 | 合并损益表，全年 | 478,834 | 416,161 | 15.06% | [本期 f-76](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-76) · [比较期 f-77](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-77) |
| 净利润 | 合并损益表，全年 | 132,175 | 112,010 | 18.00% | [本期 f-112](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-112) · [比较期 f-113](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-113) |
| 经营利润 | 合并损益表，全年 | 158,063 | 133,050 | 18.80% | [本期 f-100](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-100) · [比较期 f-101](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-101) |
| 经营现金流 | 合并现金流量表，全年 | 145,097 | 111,482 | 30.15% | [本期 f-307](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-307) · [比较期 f-308](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-308) |
| 总资产 | 合并资产负债表，期末 | 404,548 | 359,241 | 12.61% | [本期 f-181](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-181) · [比较期 f-182](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-182) |
| 总负债 | 合并资产负债表，期末 | 292,455 | 285,508 | 2.43% | [本期 f-201](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-201) · [比较期 f-202](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm#f-202) |

- 全年流量的日期源于原文 context `c-1` 和 `c-17`。两期分别为 2025-09-28 至 2026-09-26 和 2024-09-29 至 2025-09-27，均为 52 周。期末余额使用 `c-19` 和 `c-20`，没有起始日期。
- 收入示例为 `(478834000000 / 416161000000 - 1) × 100`，以 `Decimal` 四舍五入到两位小数。比较前检查币种、单位、倍率、会计准则、合并范围、文档版本、相邻日期和期间长度。零或负基期、符号变化、季度与全年混用会拒绝计算。
- 每条中文解释保存两期事实 ID，由模板组合核验值、计算结果和指标含义。管理层声明栏目目前为空，文本没有使用原文叙述驱动生成或推断经营变化原因。

## 复现

项目的日常运行和 CI 只需要 Python 3.9+。本地 JS 语法检查使用 Node.js。

```sh
python3 -m hiwd_company serve --port 18765
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m compileall -q hiwd_company
node --check app/app.js
```

启动默认数据库即可复现已核验快照的完整展示。若持有本次已核验的 SEC 原文 HTML 与 companyfacts 原始 JSON，可在本地执行以下原文重放。`--db` 使用独立文件，原则上不覆盖前次材料。

```sh
python3 -m hiwd_company import-original \
  --html /local/path/aapl-20260926.htm \
  --facts /local/path/CIK0000320193.json \
  --db local-results/manual.sqlite
python3 -m hiwd_company serve --port 18765 --db local-results/manual.sqlite
```

此导入校验文件哈希、CIK、同比期间、两份数据的币种和数值。快照文件随项目提供，原始 HTML 和原始 API JSON 保留在研究目录，未纳入版本库。companyfacts 后续可能更新，版本哈希对不上时应另行审核该新响应。单次 SEC 请求可按证据所列三个官方端点复核，使用获授权的真实项目联系人和至少 1.1 秒间隔。企业策略阻止请求时应停止。`SECClient` 目前是候选适配边界，403/429、超时、MIME 和历史分页的拒绝逻辑由离线测试验证。本次现场成功沿用经过授权的低频 curl 请求执行。

## 实际界面与验收边界

主站参考、字体/字号、主题、圆角、响应式规则和组件对应见 [品牌 UI 核验](brand-ui.md)。本地实拍附件有 `apple-reader-desktop.jpg`（1440×1000 视口）、`apple-reader-mobile.jpg`（390×844 视口的整页截图）、`apple-reader-mobile-dark.jpg` 和 `apple-reader-financials.jpg`。截图为本地审阅材料。浏览器检查包括四栏目、亮/暗主题、金额单位切换、从概览定位财报行、两期原文链接及 390px 下页面宽度。

目前公告展示已核验 10-K 和覆盖不完整状态。报道显示使用许可待确认。三年年报、四期实际披露中期/季度报告、近 90 天重大公告、多市场、媒体以及持续自动更新待后续验收。

SQLite 快照按原文哈希存储，修改同一版本会报冲突，版本更正要求指定前版。当前命令只导入已审阅的 Apple 版本。生产版本审核、修订发现与并发导入策略还需要实现。

本地服务只绑定 127.0.0.1，限制 Host、Origin 和资源路径。原文不渲染进页面，解析不执行脚本，已核验事实经文本节点输出。生产仍需身份控制、域名和出站策略、独立文档解析沙箱、连接级 DNS 校验、长期限流与监控、许可复核和部署批准。没有配置支付、第三方模型、线上部署或 DNS。
