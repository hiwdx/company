# Phase 2A 港股及 A 股官方信源验证

验证日期 2026-11-27（北京时间）。 [Issue #9](https://github.com/hiwdx/company/issues/9) · [PR #8 PM 审核](https://github.com/hiwdx/company/pull/8#pullrequestreview-6086609337)

| 市场 | 产品接入结论 | 本阶段可用路径 | 尚未通过的门槛 |
| --- | --- | --- | --- |
| 美国 US | CONDITIONAL GO，限本地原型 | PR #8 已获取的 SEC 官方数据离线复跑，现有审阅快照可浏览 | 本轮未发出新的 SEC 请求。长期、跨地区、并发和生产安全仍待验证 |
| 香港 HK | NO-GO，自动财报或公告接入 | 官方原文导航 GO，腾讯、阿里巴巴和工行 H 股可查 | 披露易自动化受条款限制；IIS 和发行人 IR 的应用内缓存、显示、摘要和 AI 处理权未取得 |
| 中国内地 CN | NO-GO，自动财报或公告接入 | 官方原文导航 GO，贵州茅台和工行 A 股可查 | 公共阅读可用，未核实适用的自动化、缓存、显示和摘要授权。上交所条款有具体限制，深、北交易所条款读取得不完整 |

原文导航直接指向已核对的发行人入口或允许链接的披露平台首页，页面展示报告名称、财年结束日、样本报告期和报告币种。港股/A 股页面没有数据自动刷新、产品内原文镜像、财务解析或已导入状态。本次对港股和 A 股做了人工文档目视抽查。产品内人工导入与自动接入均为零，故每市场正式解析一份报告、五项指标及公告目录是取得许可后的验收门槛。 [许可、来源和访问失败记录](phase-2a-sources.md)

## 美股复核

| 验收 | 处理和证据 |
| --- | --- |
| 财报修订 | 10-K/A、10-Q/A 单独保存并默认隔离。部分修订不会替换已验证报告。升级时旧版自动发布的修订也会隔离，仍保留原始证据及版本。仅在候选主报表证据完整、显式审核了原版和修订版、且比较基准未变化时才可发布。审阅记录包含新增、移除、更改、受影响期间、原文和相关口径。 |
| 失败缓存 | 目录与财报分别有独立状态、核对时间和版本。临时网络或数据失败后可以重试同一申报，原先的已核验报告仍可追溯。仅已验证报告才可当作成功缓存。SEC 403/429 继续遵守源站停止规则。 |
| 财务语义 | 自动抽取要求原文主报表结构、行名、同版本标准标签和同 accession companyfacts 数值共同匹配。收入按已证实的代收税口径标注。净利润区分归母与含少数股东的合并值。银行区分期末客户存款负债、存放同业款项、净利息收入及准备金前后项目。判定不明或金额冲突时留空。 |
| 公告 | 页面明确 8-K 事项名称来自 SEC 目录，正文以原件为准，覆盖仅限已核验目录和观察窗口。台积电 6-K 保留原文及入口，未核验的附件数字继续缺失。 |

使用 Phase 1C 的真实官方缓存副本，对 Costco、可口可乐、摩根大通重新执行事实及报表行核验。与上一阶段的逐项对账相比，12 / 10 / 18 项本期和比较期事实均匹配，合计 40/40。金额、单位、期间、会计概念、原文哈希及定位均一致。40 项指可展示事实。适用本期指标仍为 20/21，可口可乐总负债缺少可核验标准标签。可口可乐的主报表 `Net Operating Revenues` 展示为“营业收入净额（报表口径）”；其股东应占利润以归母语义展示。 [逐行证据](evidence/phase-2a-us.json) · [原始独立对账](phase-1c-reconciliation.md)

本阶段 55 项本地回归通过，另在合并候选文件的本地副本上通过 62 项，包含 Phase 0 许可与探测回归。语法检查覆盖 Python、JavaScript 和启动脚本。页面通过桌面和移动视口验收，实际截图随本地评审包交付。 [回归及截图记录](evidence/phase-2a-validation.json)

## 在本机重现

```sh
sh scripts/start_local.sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m compileall -q hiwd_company scripts
node --check app/app.js
sh -n scripts/start_local.sh
```

启动与测试可在不同终端运行。在 [本地阅读器](http://127.0.0.1:18768/) 依次搜索 `00700.HK`、`09988.HK`、`600519.SH`、`601398.SH` 和 `01398.HK`，选中发行人后核对页面中的报告币种、报告期和来源。通过 `AAPL`、`MSFT`、`NVDA`、`TSM` 审阅已验证快照。若需要重放 Phase 1C，先在本机准备有权使用的官方缓存副本，包含原 `.sqlite` 和对应 `.sqlite.reports.sqlite`。原始 SEC 缓存未随评审包分发。使用本地副本的绝对路径：

```sh
env -u SEC_USER_AGENT PYTHONPYCACHEPREFIX=local-results/pycache python3 scripts/validate_on_demand.py \
  COST KO JPM --cache /path/to/sec-review.sqlite --evidence local-results/phase2a-us-replay.json
sh scripts/start_local.sh --research-cache /path/to/sec-review.sqlite
```

搜索 `KO` 并打开“财报”可核对归母利润、营业收入和原文行名。其“公告”显示目录取样范围。只在另行取得联系信息与访问授权的环境使用 `--allow-sec`，按既有 SEC 公平访问策略运行。 [SEC 公平访问](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [Phase 1C 缓存说明](phase-1c.md#核验缓存与复现)

修订复审在本机使用 `python3 -m hiwd_company review-revision --help`。用 `--research-cache`、`--cik`、`--accession` 和 `--sha` 输出候选的影响 JSON。审阅人核对原件与前后各条事实后，在完整 JSON 中补充非空 `note`，用 `--decision` 传入该文件。发布验证影响和当前基准完全匹配。部分修订继续留在待审区。测试通过合成候选覆盖审批流程，本阶段未发布真实修订。
