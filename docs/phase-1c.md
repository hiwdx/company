# Phase 1C 按需研究与官方披露

[Issue #7](https://github.com/hiwdx/company/issues/7) · 实测日 2026-11-27（北京时间）

## 盲测结果

算法于 17:59:19 冻结，首次 SEC 请求于 17:59:31 完成。三家公司均从 SEC 当日目录按代码查询，未配置发行人、财报字段映射、锚点或期望数值。冻结的事实选择器哈希与交付版本一致。第一轮摩根大通因历史分页日期冲突在本地停止。隔离冲突页后，最新财报继续采用通过校验的 recent 目录，抽取算法保持原版本。

| 查询 | 自动发现的最新报告 | 指标通过 / 适用 | 本期及比较期原文对账 | 近 90 天公告 |
| --- | --- | ---: | ---: | ---: |
| COST | 10-K，2026-08-30 | 6 / 6 | 12 / 12 | 4 |
| KO | 10-Q，2026-10-02 | 5 / 6 | 10 / 10 | 2 |
| JPM | 10-Q，2026-09-30 | 9 / 9 | 18 / 18 | 4 |

总体 20/21 个适用本期指标通过，1/21 缺失（4.76%），没有数值冲突通过展示。已展示的 40 个本期及比较期数值全部经正式报表独立抽验。单独的合成负例验证了数值冲突、同 accession 旁证缺失、原文主体、重复锚点、数字格式及凭证哈希等拒绝路径。Costco 另在真实页面触发 2026-05-10 历史 10-Q，复用目录和 companyfacts，新增一个原文请求。 [逐项对账](phase-1c-reconciliation.md) · [适配器收据及冻结记录](evidence/phase-1c-sec.json)

SEC 的官方公司名称和证券代码通过同一目录查询，CIK 与证券分开。搜索目录有观察日期。未收录的中文别名可使用证券代码或官方名称查询。既有已审阅公司快照继续可读，来源标记与自动结果区分。 [SEC 目录与公平访问](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

## 历史和公告窗口

按美东申报日期核验 400 天历史和 90 天公告。本次 90 天窗口为 2026-08-30 至 2026-11-27。截止日来自实际获取时间与可用的 HTTP Date，取较早日期。同日观察时点后的可能申报不在本次证据内。

摩根大通归档 001 清单给出的末日为 2025-11-24，实际页内最后一条申报日为 2025-11-25，两者条数同为 2,108。该页及其后续待读页保持缺口，400 天不标为完整。recent 有 26,393 条，起点 2025-11-26，独立覆盖本次 90 天窗口及最新定期报告。Costco 和可口可乐的声明分页与 400 天窗口无交集。程序核对目录数组、报告类型、日期、页序号、条数和跨页重复，缺页或不一致时收缩可声明窗口。 [实际时间窗与归档差异](evidence/phase-1c-sec.json)

公告按 accession 去重，区分 8-K、8-K/A、6-K 与 6-K/A，并保留 SEC 事项代码、申报日及原文。8-K 的中文短句来自监管事项分类。6-K 显示外国私人发行人报告，缺少具体目录事项时保留原文入口。未赋予严重程度，也未依据标题推断经营变化。现场按目录核验 10 条美国发行人 8-K，并抽验三个正文入口。对台积电上阶段官方目录的离线重放另验证了 12 条 6-K，附件数字仍待核验。 [Form 8-K](https://www.sec.gov/files/form8-k.pdf) · [Form 6-K](https://www.sec.gov/files/form6-k.pdf) · [Costco 公告](https://www.sec.gov/Archives/edgar/data/909832/000090983226000134/cost-20261107.htm) · [可口可乐公告](https://www.sec.gov/Archives/edgar/data/21344/000162828026067403/ko-20261027.htm) · [摩根大通公告](https://www.sec.gov/Archives/edgar/data/19617/000162828026065582/jpm-20261013.htm)

## 核验、缓存与复现

当前自动财务提取适用于受支持的美国本土 10-K 和 10-Q。用原文中可见的标准 iXBRL 标签、CIK、表单、期间、非分部上下文和报告币种选候选，在同一 accession 的 companyfacts 中核对数值，再以原文实际锚点生成引用。银行按 SEC SIC 进入存款、利息与信用损失等指标。修订保留独立表单和版本，等待更正验证时保留旧证据。

目录缓存 24 小时，近期目录和 companyfacts 缓存 6 小时，原文 7 天。来源响应缓存保留体积上限 96 MiB，单响应上限 24 MiB。一次仅运行一个按需研究，用户触发前不抓取财务或公告。所有请求统一至少相隔 1.1 秒，遇到 403/429 停止该进程新的 SEC 请求。缓存按观察日期说明新鲜度。财务解析在子进程运行，外部输入限额、时间上限，并阻断访问文件和网络的 Python 审计事件；Linux 另限制进程内存。用同一批缓存原件重跑三个样本，40 个值一致，新增 SEC 请求为零。

本地运行及回归：

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m hiwd_company serve --port 18767
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m compileall -q hiwd_company scripts
node --check app/app.js
```

联网复测前先在本机设置获授权的 `SEC_USER_AGENT`，包含真实项目名称 `hiwd company` 和项目联系地址。然后执行：

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 scripts/validate_on_demand.py COST KO JPM \
  --cache local-results/sec-review.sqlite --evidence local-results/sec-review.json
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m hiwd_company serve --port 18767 \
  --research-cache local-results/sec-review.sqlite --allow-sec
```

使用同一缓存去掉 `--allow-sec` 可审阅现有缓存而不发 SEC 请求。公开测试证据仅包含精选数字、结构化状态、来源时间、URL 与哈希。上游完整文件、审核截图和联系地址均通过对应本地或原来源管理。 [页面和回归验收记录](evidence/phase-1c-validation.json)

## 产品与发布边界

中文解读由可追溯事实和确定性计算组成。自动经营叙事、业务分部和管理层归因语义仍待核验，本阶段不展示未核验归因。权威媒体使用许可、全市场覆盖、长期运行、跨出口接入、生产多实例限流以及操作系统级解析隔离仍待验收。页面延续现有 hiwd.com 的字体、主题、排版与组件。

PR 以 #6 为基线，供 PM 审阅本阶段增量。按 PO 批准依次处理 #2、#4、#6，再将本 PR 对准 main 并重跑完整 CI。三份旧 PR 的 README、品牌文档与 ignore 重叠处理沿用 Phase 1B 方案，保留 Phase 0 证据和两套回归。 [PR #6 审核](https://github.com/hiwdx/company/pull/6#pullrequestreview-6086323153) · [合并依赖及冲突处理](phase-1b.md#pr-顺序)
