# Phase 1B 通用公司财报阅读器

[Issue #5](https://github.com/hiwdx/company/issues/5) · 实测日 2026-11-27（北京时间）

## 样本与覆盖

| 查询示例 | 发行人 CIK | 已核验披露 | 财年及币种 |
| --- | --- | --- | --- |
| AAPL、Apple、苹果 | 0000320193 | 2024–2026 财年三份 10-K、截至 2025-06-28、2025-12-27、2026-03-28、2026-06-27 的四份 10-Q | 9 月附近结束，美元，US GAAP |
| MSFT、Microsoft、微软 | 0000789019 | 2026 财年 10-K | 2026-06-30，美元，US GAAP |
| NVDA、NVIDIA、英伟达 | 0001045810 | 2026 财年 10-K | 2026-01-25，美元，US GAAP |
| TSM、TSMC、台积电 | 0001046179 | 2025 财年 20-F 及截至 2026-09-30 的 6-K 与财务附件 | 20-F 为 IASB IFRS、新台币。6-K 附件按台湾认可的 IAS 34、千元新台币 |

SEC submissions 的 CIK、证券代码和交易所已比对。TSM 为 NYSE 上市的 ADS，每份代表五股普通股，2330 为 TWSE 普通股。同一发行人标识可关联不同证券。两者的名称和代码均通过同一查找流程，快照只覆盖表内的四个样本。候选歧义时须选择发行人。 [身份映射及查询元数据](evidence/phase-1b-sec.json) · [TSM 20-F 封面](https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm)

10 份报告每份各六项本期指标，比较期原表明细一同留档。4 份最新年报另有经营概览、收入构成和标为管理层归因的中文摘要，均可定位官方报告。台积电 6-K 及其附件已验证表单、币种与报告期，附件财务数据当前为待核验。 [原文对账](phase-1b-reconciliation.md)

## SEC 实测及覆盖证据

- 本机 Darwin arm64、Python 3.9.6，获授权的真实项目联系信息只用于 SEC 请求。使用实际 `SECClient`，序列请求相隔至少 1.1 秒。403 与 429 各自保留状态并停止该批次，不切换出口。
- 第一次完整 Apple 路径于 17:30:36 开始。独立进程于 17:34:15 复测。两个时点的 Apple 目录、companyfacts 和 FY2026 10-K 各返回 HTTP 200，原文和事实响应哈希一致，均通过适配器回执→原文解析→SQLite→阅读模型重放。四家公司共 11 份披露重放通过，第二次 Apple 重放确认幂等。
- Apple 核验窗口为 2024-10-01 至 2026-11-27（申报日期）。recent 的 1007 条记录自 2015-10-07 起，数组长度一致且 accession 无重复。SEC 目录列出的归档分页为 1994-01-26 至 2015-10-05，与本次窗口不交叠。窗口内找到 3 份 10-K、6 份 10-Q，选取最近 4 份实际 10-Q，而非合成年报季度。末次观察日用于封闭窗口，未来完整性未作推断。
- 初始目录校验曾把股东大会日期当财务期末，后来也发现 6-K 本地事件日期可比美东提交日晚一天。两次均为本地校验中止，SEC 没有拒绝。适配范围已按正式报告表单和 6-K 事件语义纠正。两次正式样本代表短时段可达性，跨环境、持续更新及生产许可仍待验证。 [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [请求摘要](evidence/phase-1b-sec.json) · [端到端重放](evidence/phase-1b-replay.json)

## 本地复现

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m hiwd_company serve --port 18766
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m compileall -q hiwd_company scripts
node --check app/app.js
```

应用运行时只读本地 SQLite；初次启动导入项目核验快照。实体以 CIK，文件版本以 CIK、accession 和原文 SHA-256 定位。版本更正须指定当前的上版，旧版可按标识读取。原 Phase 1 SQLite 的当前快照在迁移时保留；其旧修订仍可在原表审计。

需重新取原件时，先设置真实且获授权的 `SEC_USER_AGENT`，其格式为项目名称 `hiwd company` 加联系地址。以下示例仅在审批允许时手动运行，各次目录必须为新路径：

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 scripts/probe_sec.py --output local-results/sec-first --as-of 2026-11-27
PYTHONPYCACHEPREFIX=local-results/pycache python3 scripts/probe_sec.py --sample repeat --output local-results/sec-repeat --as-of 2026-11-27
PYTHONPYCACHEPREFIX=local-results/pycache python3 scripts/replay_sec.py --batch local-results/sec-first --batch local-results/sec-repeat --db local-results/replay.sqlite
```

观察日应改为实际当地日期。SEC 当前返回的字节若变化，旧快照原文哈希检查会拒绝重放，须重新核验。2026 财年 Apple 上阶段的原文哈希和本阶段所获版本不同，数字与选取锚点一致，旧记录保留。

人工导入使用已合法取得的本地文件，来源状态独立。本轮实际重放 Apple 2026 财年第三季共 12 项数值，CLI 输出 `live_api_success: false`。

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m hiwd_company import-original \
  --snapshot data/reports/0000320193-26-000020.json \
  --html /local/path/aapl-20260627.htm \
  --facts /local/path/AAPL-facts.json \
  --index /local/path/AAPL-submissions.json \
  --db local-results/manual.sqlite
```

## 页面及发布边界

33 项本地测试通过。真实财报快照测试与异常合成测试分开。浏览器验证了公司名称及代码查询、歧义候选、方向键与回车、报告切换、单位、原文链接、未知公司、暗色、公告和报道状态、报告直达链接及 390px 下页面宽度。截图位于本地审阅包。 [验收记录](evidence/phase-1b-validation.json)

财务事实来自审阅过的原文与结构化选择配置。程序核验主体、目录、窗口、证据版本、期间、币种、单位、倍率和符号。期末资产负债比较不把上财年末冒充上年同期，累计现金流和单季分别呈现。未经单独核验的披露和字段显示待核验，媒体显示使用许可待确认。

本阶段面向四发行人的有限目录。任意发行人接入、报告选择配置自动生成、6-K 附件数值解析、其余报告的经营摘要、90 天公告覆盖、媒体或其他市场许可，留待后续验证。界面无付费模型调用。生产上线还需要解析隔离、持续限流与监控、修订发布策略和数据使用审批。

## PR 顺序

[PR #2 PM 复审](https://github.com/hiwdx/company/pull/2#pullrequestreview-6086009426) 接受 Phase 0 文档。[PR #4 PM 初审](https://github.com/hiwdx/company/pull/4#pullrequestreview-6086009752) 对单报告原型条件通过。本分支以 #4 为审阅基线，便于只看 Phase 1B 增量。

建议按 PO 批准依次处理 #2、#4、Phase 1B。#2 与 #4 的重叠路径为 `README.md`、`docs/brand-ui.md`、`.gitignore`。处理 #4 时保留两阶段 README 入口、保留品牌文档中双方核验内容，并合并 ignore 条目。Phase 0 报告、数据合约、脚本、离线测试和原始验证记录应一并保留。#4 合并后再将 Phase 1B 的目标分支切到 main，并重新运行两套检查。如使用 squash，在重新定目标前需先基于 main 重放 Phase 1B 的独立提交。
