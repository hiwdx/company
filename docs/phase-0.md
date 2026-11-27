# hiwd company · Phase 0 — 数据源可行性验证与 MVP 技术建议

任务：[Issue #1](https://github.com/hiwdx/company/issues/1)。实测日期：2026-11-27（Asia/Shanghai）。Tech Lead 提交，待 ChatGPT PM 审核、Product Owner 最终验收。

## 1. 决策：CONDITIONAL GO

**可以推进“美股官方披露单路径验证”，不能据此开始三市场完整产品或承诺数据覆盖。**

- 腾讯 WeStock CLI 确实可运行，六个样本均取得搜索候选、公司名称、四期三表及财务类公告索引。但来源追溯、币种语义和产品使用授权尚不满足生产条件。建议仅保留为可关闭的检索补充层；不依赖它生成已核验财务事实。
- SEC 有明确的官方 JSON 接入路径；本环境对 `www.sec.gov` 和 `data.sec.gov` 的真实请求均返回 **403**，端到端原文与 XBRL **没有通过**。在解决合法访问前，不宣称美股已打通。
- HKEXnews 网站条款限制程序化访问及文本/数据挖掘，未取得相关许可；港股自动采集暂为 **NO-GO**，优先评估 IIS 或有权提供公告内容及 AI 使用权的服务商。
- A 股公开披露可检索；巨潮官方数据服务、交易所深链接及持续自动化使用的范围尚待确认。公司 IR 可作为候选补充，不等于已取得全站采集许可。
- 全部条件未满足时，替代交付是本地、人工核验的原文目录和证据链原型；不是用腾讯镜像冒充官方披露，也不擅自缩减三个市场的最终产品目标。

本阶段没有完整 UI、账号体系、行情/交易/社区功能、投资评级或买卖建议；没有购买、正式部署或修改 `company.hiwd.com` 的 DNS。

## 2. 方法、证据与限制

运行环境：本机 macOS arm64、Python 3.9.6、curl；GitHub 通过已连接的 `hiwdx` 账号操作。起始仓库无提交/分支，按 Issue 的最小初始化例外在 main 创建仅含产品边界的 README；调研内容均放独立分支。

真实探针在 [scripts/probe.py](../scripts/probe.py)，运行说明在 [reproduce.md](reproduce.md)。结果分开保存：

- [腾讯首次实测](evidence/westock-2026-11-27.json)：16:28:50–16:31:55，共 36 次 CLI 调用（含版本检查）。
- [腾讯定向复核](evidence/westock-followup-2026-11-27.json)：16:32:15–16:33:54，共 19 次调用（含版本检查），修正诊断解析并补全六个详情链接。
- [SEC 实测](evidence/sec-2026-11-27.json)：16:28:49 起；2 次 HTTPS GET 均 403，TSM 后续调用按主机拒绝策略跳过。
- [发布包溯源](evidence/westock-provenance.json)：平台认证信息、内容验签与二进制校验摘要。
- [来源核验台账](evidence/source-checks.json)：官方政策、IR 目录及文档的人工观察摘要；明确区分 web 索引、直接读取和浏览器观察。
- [本地验证记录](evidence/validation-2026-11-27.json)：7 项离线回归、语法编译和证据 JSON 格式检查；不代表上游通过。固定 CLI 下载器也已现场成功运行并取得相同二进制 SHA256。

证据 JSON 留存时间、脱敏命令、退出码、字节数、stdout/stderr SHA256、字段名、少量身份/日期/链接元数据；不提交财务数值表、公司介绍、受限原文、凭据或 Cookie。哈希用于比对一次响应，不代表独立证明数据正确。`tests/fixtures/` 仅含显式标注的合成样本，不能证明服务可用。

**已知探针限制及修正**：首版将“失败: 0”误判为错误，将港股介绍中的换行误认为新表头，只识别 HTTPS，且忽略带连字符的港股公告 ID。首版异常摘要保留并注明；错误的港股伪表头已移除以免复制叙述内容，响应哈希未修改。复核版只认合法 Markdown 表头，区分非零失败，接受 HTTP 链接作为诊断证据，并补测港股详情。港股 profile 多行及含竖线标题仍可能无法完整解析，因此 `row_count=0` 不等于供应商无数据。此文本解析器仅用于诊断，不能成为生产财务适配器。

本机出口的实际地域未核实；没有第二地区的受控运行环境。web 检索/缓存可读不能当作另一区域的 API 实测。大陆、香港/新加坡、美国的跨地区连通性、延迟及稳定性均未验收。403 的原因没有得到 SEC 确认，不能归因为某一地区或某个头字段。

## 3. 腾讯 WeStock：文档声称与实测

### 3.1 官方发布路径与安装

从 [SkillHub 包元数据](https://api.skillhub.cn/api/v1/skills/westock-data?namespace=tencent-adm) 发现 `@tencent-adm/westock-data`，认证发布者名称为腾讯自选股、认证主体为腾讯科技（深圳）有限公司。实际包 `_meta.json` 为 **1.0.7**，其脚本固定发布源为 `https://stockbuddy.qq.com/release/skillhub/cli/v0.0.2/`。不能把第三方教程的 npm 包 `westock-data-clawhub@1.0.4` 当作本次测试对象。

官方包提供 shell、PowerShell、Node 安装脚本；默认装到用户目录且 shell 脚本可能改 PATH。本次审阅后直接下载到工作目录，未运行全局安装。CLI 实际版本为 `westock 0.0.2 channel=skillhub`。发布清单和二进制 SHA256 均匹配固定值；SkillHub 官方验签工具返回本地验签及内容指纹匹配成功。其签名字段 `publisher_real_name_verified=false` 与目录的组织认证是不同字段，不能把平台内容签名解读为数据使用授权。目录还存在 `latestVersion=1.0.7`、`tags.latest=1.0.4` 的不一致，故固定内容指纹和 CLI 版本。

[官方安装说明](https://skillhub.cn/install/skillhub.md)、[验签说明](https://skillhub.cn/docs/verify-signature?namespace=tencent-adm&slug=westock-data&version=1.0.7)。本仓库的 [prepare_westock.py](../scripts/prepare_westock.py) 仅下载并检查已审阅的内容及二进制，不执行包中的安装指令。内容改变即停止，不能自动追新或跳过校验。

### 3.2 认证、许可、额度、价格与 MCP

| 项目 | 文档/观察 | 本次结论 |
| --- | --- | --- |
| 身份认证 | 包目录标记不需 API key；0.0.2 帮助无 auth 子命令 | 本次没有提供 token、登录或授予账号权限，测试命令成功返回；不推断所有版本/数据均免登录 |
| 只读能力 | search/profile/finance/notice | 已实测；未触碰模拟交易、持仓或自选列表 |
| 输出 | 包说明为 Markdown 表格 | 实测为表格、中文批处理状态、自由文本/PDF 地址混合；未发现可据此承诺的稳定 JSON 合约 |
| 服务端/定时任务/转展示/缓存/AI 摘要许可 | 安装文档没有给出足够的明确授权 | **未验证，生产默认禁用**；不以可执行、免密钥、开源或个人使用替代授权 |
| 配额、限流、SLA、价格 | 已审阅包及公开入口未提供可确认数值 | **未知**；本次主动间隔至少 1.1 秒，不做压测、不声称免费无限量 |
| MCP | 本会话工具没有腾讯自选股连接器；未核实官方可直接连接的 MCP 地址/部署协议/权限 | **未验证**；没有把 CLI 成功记作 MCP 成功，也没有使用第三方仿制 MCP |

待供应方确认的最小范围：证券检索、公司身份、财报和公告的只读权限；服务端无人值守、保存期限、私人网页展示、中文事实摘要及向模型传送内容的权利；额度、价格和终止/撤销机制。如需认证，由 PO 在官方渠道自行完成登录/审批，密钥置于 secret store，只给隔离后端使用；不授予交易、自选写入或账户资产权限。当前 0.0.2 无需进行这些人工登录操作，也不能引用其他版本的 `auth fetch` 教程代替实测。

### 3.3 逐样本能力矩阵

“返回”仅说明 CLI 有输出；“核验”要求官方身份及原文证据通过。四期是供应商序列，**不是四份实际披露文件已验收**。

| 市场/样本 | 代码、英文、中文搜索 | 公司身份 | 财报/日期/币种实测 | 公告及追溯 | 权威核验状态 |
| --- | --- | --- | --- | --- | --- |
| US AAPL | AAPL/Apple/苹果均含 usAAPL；Apple 另含 APLE | profile 返回 Apple Inc. | 三表各 4 行；EndDate 最新 2026-09-30，DisclosureCurrency=USD | 财务索引最新 11-03；普通公告有 11-25；详情为腾讯 HTTP 镜像 | SEC 403；报告期、金额、发布日期未获原文交叉核验 |
| US TSM，非美籍 ADR | TSM/英文全名/台积电均含 usTSM；混有 TSMWF 等 | profile 返回 Taiwan Semiconductor Manufacturing；不能用 GP 类型推导 ADR 比例 | 三表各 4 行；最新 2026-09-30；**TWD**，与包“美股美元”概括不同 | 财务类型索引最新仅 2026-04-16；普通公告有 11-25；腾讯 HTTP 镜像 | SEC 后续按主机拒绝跳过；IR 年报目录可读，数值/单位未核验 |
| HK 00700.HK | 00700/Tencent/腾讯控股均含 hk00700；含 80700/TCEHY 等 | profile 返回腾讯控股有限公司；多行 Markdown 不适合直接入库 | 三表各 4 行；最新 2026-09-30；CurrencyType=港币 | 财务索引最新 11-18；详情为腾讯 HTTP 镜像 | HKEXnews 自动接入授权阻塞；官方结果文件的 web 索引指示 RMB，存在币种语义冲突 |
| HK 09988.HK，跨市场/不同财年 | 09988/Alibaba/阿里巴巴均含 hk09988；含 89988/BABA 等 | profile 返回阿里巴巴集团控股有限公司 | 三表各 4 行；最新 2026-09-30；CurrencyType=港币 | 财务索引最新 11-19；普通列表存在多行解析缺口；腾讯 HTTP 镜像 | 官方 IR PDF p1 标示 RMB 主金额及 USD 便捷折算，不能把港币字段视作已核验披露币种；3 月财年终结 |
| CN 600519.SH | 600519/英文名/贵州茅台均含 sh600519 | profile 返回贵州茅台；仍需法定主体 ID | 三表各 4 行；最新 2026-09-30；默认表缺币种列 | 财务索引 time=10-30，IR 目录标 10-31；不能直接合并日期；腾讯 HTTP 镜像 | IR 目录可读；交易所/巨潮生产授权、原文逐项核验待完成 |
| CN 601398.SH，A/H 银行 | 601398/工商银行含 A 股；**ICBC 英文搜索仅返回 H 股/场外候选，没有 sh601398** | profile 返回工商银行；银行报表不可套工业公司模板 | 三表各 4 行；最新 2026-09-30；默认表缺币种列 | 财务索引最新 10-30；普通公告到 11-12；腾讯 HTTP 镜像 | 官方 IR 可见 A/H 不同版本及发布时间；数值和会计准则未完成逐项比对 |

复核三次 finance 批量调用各返回 3 张表 × 8 行，合计 72 行；未发布其中数值。三市场财务公告列表各返回每标的 2 条，12 条的 `url` 都为空；再取每标的 1 个详情，**6/6 返回 `http://file.finance.qq.com/...PDF` 地址**，不是权威原文链接，未跟随或擅自改写 HTTPS。与包说明“A 股详情为全文”的表述也不同。`time`、`update_time` 无时区；财报表仅 EndDate，缺直接关联原文、披露日期、单位倍率、会计准则和修订标识。不得把抓取时间当披露时间，把上市币种当记账币种，或将镜像哈希当官方签章。

原文对照线索：[腾讯 3Q2026 文件](https://www.tencent.com/wp-content/uploads/2026/11/E700_3Qresults.pdf) 的 web 索引第 9 页标 RMB in millions，但直接 web 打开未返回可读 PDF，因此只记索引线索；[阿里 2026-09 季度及中期结果 PDF](https://data.alibabagroup.com/ecms-files/1532295521/332cda08-6a83-4bf7-86af-2ef3b348596d/Alibaba%20Group%20Announces%20September%20Quarter%202026%20Results%20and%20Interim%20Results%20for%20the%20Six%20Months%20Ended%20September%2030%2C%202026.pdf) 已直接读取，p1 显示 11-19 发布、报告期及币种。这里仅说明字段冲突，**未证明供应商金额是否经过汇兑，也不判定其金额错误**；在取得转换方法/倍率/时间之前隔离该数据。

## 4. 权威原文路径与合法接入边界

| 渠道 | 公开路径/规则 | 实测与决策 |
| --- | --- | --- |
| SEC EDGAR | [官方 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)：submissions、companyfacts、companyconcept、历史分页；无 API key，不支持 CORS；[访问政策](https://www.sec.gov/about/webmaster-frequently-asked-questions)要求声明 User-Agent，最大 10 req/s | 实测两个主机 403；立即停止同主机后续调用。计划服务端访问、共享节流初始 1 req/s，拒绝后停止并联系官方排查；不轮换 UA/IP/代理绕过。已有 API 文档不等于本环境连通 |
| HKEXnews | [网站条款](https://www2.hkexnews.hk/Global/Exchange/Terms-of-Use?sc_lang=en)；[IIS 正式服务](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29?sc_lang=en) | 条款不支持本项目无授权自动访问/文本挖掘；未抓网页内部接口或 PDF。IIS 需订阅/认证测试，回溯与 AI 处理权限还需单独确认，未申请或购买 |
| 巨潮资讯/深证信 | [巨潮首页](https://www.cninfo.com.cn/new/index?islogin=false)及页脚声明；[官方数据平台](https://webapi.cninfo.com.cn/)、`#/apiDoc`、数据商城 | HTTP 首页及浏览器主页可读；API 文档目录在本次浏览器观察时未加载出内容，只有空表；数据商城也未返回产品条目。未持 API 授权，实际数据 API/配额/价格均未验证；未以网页私有接口替代正式服务 |
| 上交所 | [法律声明](https://www.sse.com.cn/home/legal/) | 允许规定范围的非商业浏览/下载；牟利使用及链接有条件，声明要求链接首页。不能默认允许产品深链接及长期数据库。未调用 query.sse 等未证实接口；生产接入待书面确认或授权服务 |
| 深交所 | [法律声明](https://www.szse.cn/application/laws/index.html) | web 工具超时后本机 curl 正常读取法律页；同样存在非商业用途及首页链接条件。仅法律页面可读不等于公告 API 已通过 |
| 北交所 | [官网](https://www.bse.cn/)、[法律声明](https://www.bseinfo.net/about_neeq/legal_disclaimer.html) | 官网 web 返回无可读正文；声明可读，非商业浏览与首页链接限制需纳入；无 API 额度/授权确认，不承诺北交所覆盖 |

IR 必须按法定公司绑定域名，单独记录条款和允许的取用范围，不能通过 IR 绕过已拒绝的官方数据服务。当前观察：

- Apple：[网站条款](https://www.apple.com/legal/internet-services/terms/site.html)存在自动取用限制；未抓该站财报，SEC 路径保持阻塞状态。
- TSMC：[年报目录](https://investor.tsmc.com/english/annual-reports)可读，列有 2025/2024/2023 年报及对应 20-F 发布日期；这是目录验证，全文提取/AI 使用范围未确认。
- 腾讯：[IR 目录](https://www.tencent.com/en-us/investors/financial-reports.html)直接 web 无可读正文；结果 PDF 的索引线索见上，不能记作成功的自动采集适配器。
- 阿里：[年报目录](https://www.alibabagroup.com/ir-financial-reports-financial-results)可读，FY2026/2025/2024 可见；[官方 FAQ](https://www.alibabagroup.com/en-US/faqs-financial-reporting)说明 3 月 31 日财年终结；单份季度 PDF 已读取。持续抓取/模型使用许可未确认。
- 茅台：[IR 财报目录](https://www.moutai.com.cn/mtgf/tzzgx/cwbg/index.html)可读，列有 2026 Q3、H1、Q1、2025 年报等，列表日期与腾讯 time 不完全相同；法律日和时区待核对。
- 工行：[IR 财报目录](https://www.icbc-ltd.com/ICBCLtd/Investor%20Relations/Financial%20Information/Financial%20Reports/)可读；2025 年报、2026 中报、Q1/Q3 与 A/H 文档分别记录，不可当重复错误删除。

IR、巨潮及交易所没有在本次核验资料中提供可确认的通用采集频率上限；**未知不是无限制**。许可未明确时不启动后台轮询。授权后按协议设置，缺省提议每源串行、至少 2 秒间隔、每天有限次更新；这是设计值，不是供应商公布值。

SEC 公开脚本访问政策也不能被解释为所有发行人文件均无版权；全文引用、缓存、展示及向模型发送内容仍需确认适用权利，按必要范围引用。本次 User-Agent 用项目 Issue 作联系地址；是否满足 SEC 示例中的管理邮箱要求尚未确认，后续由运营者提供真实管理邮箱并先通过官方支持排查，不能把这次 403 解释成 SEC 不提供开放 API。

## 5. 媒体白名单：信誉审核与权利审核两道门

候选为 Reuters、Bloomberg、FT、WSJ、财新。候选名单不自动启用。每家维护域名/栏目/内容类型、许可依据、有效期、地区、摘要/标题/缓存/AI 权利和复核人，初始 `enabled=false`。

[Reuters 正式许可入口](https://reutersagency.com/license-reuters-content/)存在，具体内容和 RAG 权限需询价，未取得授权。Bloomberg 未获书面许可前关闭自动采集（[条款](https://bloomberg.com/tos)）。FT、WSJ、财新的具体采集许可、付费可用性与价格未验证；不把个人阅读订阅当后端许可。不购买、不绕付费墙、不从缓存/转载站恢复受限文章。

仅对获准使用的内容提取可核验事实、时间和原文链接，采用自己的短摘要，不转载全文。按 `issuer + event_type + event_date + primary_document/event_id` 聚类，同一报道多版本保留版本关系；转载/新闻稿的共同来源只算一个来源。新闻稿即使出现在权威媒体网站仍标 `company_statement`；法定披露标 `regulatory_disclosure`，独立采写标 `independent_reporting`。排除自媒体、股评、目标价、评级、传闻与匿名“市场消息”；来源不足即不生成报道结论。

## 6. 数据模型、适配器与事实约束

详细设计见 [data-contract.md](data-contract.md)。基本原则：发行人和证券分开；ticker 保存字符串并带市场/交易所命名空间；跨上市、ADR、双柜台保留关系及证据；法定报告日期、原文发布时间、接收时间、抓取时间互不替代。

每个数值必须携带报告起止日期、口径、币种、单位倍率、准则、合并范围、原文版本与证据定位。未知为 null 并注明原因，禁止默认推算。修订不覆盖历史值；来源冲突进入待核验队列。计算使用 Decimal 等确定性代码及可比性校验，模型只解释经验证的事实包。

每项实质性结论附可打开的证据定位；公司管理层的归因原样标“公司表示”，不能成为系统确认的因果。解释只说明已有事实，不预测、荐股、评级或给买卖建议。缺原文、币种/单位冲突、过期、修订待复核时停止生成相关结论。未披露、未找到、访问失败、无权限和不支持分别展示。

## 7. 技术架构建议与成本

**优先建议：先做本地 Python 采集/核验模块 + SQLite 证据目录；Phase 1 验证通过后再选轻量容器后端 + 响应式 PWA。** 原因是官方 HTML/XBRL/PDF 处理与隔离需要常规运行环境；腾讯目前是 Go 二进制且生产授权未解决，不能预设它是所有运行时的基础。

- 采集、原文解析和核验运行于受控后台；队列初期用 SQLite 任务表和单 worker 即可，按内容哈希幂等。数据量/并发增加后迁移 PostgreSQL 和独立队列，不提前引入微服务/向量数据库。
- 前端候选 TypeScript + React + Vite 静态 PWA，与后端 JSON API 解耦；先本地窄屏/桌面一页路径。完整框架及 UI 设计待数据验收，不在 Phase 0 实现。
- 增量以 source document ID/accession + version/hash 为键；官方支持时使用 ETag/Last-Modified，SEC 历史文件按需分页，三年回填一次。按许可缓存原文；仅已核验事实供读取。失败保留上次成功状态、来源截止日、抓取失败时间；禁止回退生成虚构新内容。
- Cloudflare Workers + Static Assets 可作为 PWA/API 候选，D1 存元数据、R2 存授权文档；本阶段不创建资源。[Workers 限制](https://developers.cloudflare.com/workers/platform/limits/)包含 128 MB 内存等约束，不能据此承诺原生 CLI 或重型 PDF/OCR 能在普通 Worker 内运行；若选择该方案，解析服务独立并计成本。
- Fly.io 或通用 Linux 主机适合运行采集与解析容器，可先单机 SQLite 加加密备份；没有验证 Fly 出口可访问 SEC，也没有验证地区性能，不能用“部署美国”作为绕过 403 的方案。选择地域需先满足供应方政策并复测。
- 私人访问：上线前用现成身份代理或 VPN 控制所有静态页/API/原文端点，禁止仅隐藏 URL。只放行 PO 身份，默认拒绝；源站直达同样受保护。PWA service worker 默认只缓存应用壳，私有正文/API `no-store`，退出清除本地私有数据。无需自建注册/密码系统。
- 密钥只进入后端 secret store，分开发/生产，限制只读、短期凭据、可撤销；日志不含请求头/token/签名 URL；仓库忽略 `.env`，提交前检查秘密与原文。
- 文档安全：来源内容均为不可信数据；抓取工具只接受供应方文档 ID，不接受模型生成任意 URL；精确 HTTPS 主机/路径白名单、禁止 userinfo/非标准端口，DNS 解析和每次重定向均阻断内网/loopback/link-local/metadata IP，连接时防 DNS rebinding；限体积、超时、MIME 校验。解析放无网络的受限进程，禁宏/脚本/外部资源，HTML 清洗，原件不内联执行。文档中的“忽略指令/上传密钥”只当文本；模型不拥有 secrets 或任意网络/代码执行权限。探针仅是固定端点诊断，不声称已经实现上述生产防护。

成本均为 **2026-11-27 参考预算，非报价或购买承诺**：

| 项目 | 依据与估算 |
| --- | --- |
| Phase 0 | 未购买新服务；本机运行和本次工具使用未做费用审计，不声称总成本为零 |
| 本地验证 | 不新增托管开销；模型/授权费用另计 |
| 容器方案 | [Fly 当前价格页](https://fly.io/pricing/)示例最小机器约 USD 2.19/月；解析所需内存需测量。建议为机器、存储、备份及流量预留 **USD 10–25/月**，不是高可用配置报价；税费/地区价另算 |
| Cloudflare 候选 | [Workers 价格](https://developers.cloudflare.com/workers/platform/pricing/)Paid 起 USD 5/月；静态/数据库/对象存储/解析服务按实际用量另算。粗预算 **USD 5–15/月 + 独立解析服务**，尚未压测 |
| 模型 | 仅对新文档摘要；月费 = 输入 token × 供应商输入价 + 输出 token × 输出价。模型尚未选定，不引用过时单价；首月提议上限 USD 10，由 PO 批准后才启用付费调用 |
| 数据 | 腾讯/巨潮及媒体许可未知，必须单独预算；SEC 官方读取不需 API key。HKEX [公开价目](https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-%28Hong-Kong%29/Market-Data/Market-Data-Vendors?sc_lang=en)列 IIS Redistribution Fee HKD 45,000/季，**不代表私人使用实际报价，也不含本项目 AI 权利确认**；不建议为验证直接购买 |

跨地区验收必须在获准的既有环境进行：大陆浏览器、香港/新加坡后台候选、美国后台候选分别记录地区依据、请求时间、状态、TLS、延迟和正文类型；每处低频两轮即可，不做压力测试。任何拒绝转官方支持/授权流程，不用换出口继续抓取。未获部署/付费批准时只交测试方案与缺口，当前不能宣称选定地域达标。

## 8. Phase 1 提案与 PM 验收门槛

只在本 PR 获审后开始下一阶段。估时是单人工作量，不含授权/供应方等待。

1. **P1-0 接入前置（0.5–1 天 + 外部等待）**：通过 SEC 官方支持核查本次 403（真实项目 User-Agent/联系人、现有出口、时间与状态）；取得允许的访问方式后再复测。同步向腾讯/HKEX/巨潮确认限定用途与报价，由 PO 决定是否申请/购买。没有访问条件时后续端到端任务标阻塞，不能换源冒充通过。
2. **P1-1 一条美股官方链路（2–3 天）**：AAPL 搜索/CIK 经官方资料确认 → submissions/历史文件 → 原文 → XBRL facts → 证据定位 → 确定性计算 → 中文解释 → 本地四栏目页面。验收：一份报告 5 个核心指标均回链至同一官方文档及上下文；币种、倍率、财年/单季/累计、GAAP、版本均明确；未披露与失败区分；503/403/修订不会生成伪新结论。此门槛当前未通过。
3. **P1-2 历史与非典型美股（2–3 天）**：AAPL 最近三年年报、最近四期实际 10-Q；TSM 的 20-F/6-K/IR 披露周期单独处理，不要求外国发行人虚构 10-Q。测试不同财年、ADR/普通股、货币/倍率、重复事实和修订；历史文件分页去重不漏。
4. **P1-3 港股扩展（2–4 天，授权后）**：00700/09988 官方或获准披露 feed → 原文证据；检查人民币报告币种、双柜台、阿里 3 月财年、年报/中报/季度业绩公告差别。验收必须有许可依据、原文链、日期/币种/单位核对；腾讯结果只能提供线索。未获许可则保持该适配器关闭并向 PM 明示差距。
5. **P1-4 A 股扩展（2–4 天，接入范围确认后）**：600519/601398；年报、半年报、季度报告和近 90 天公告；银行模板、A/H 多版本、币种缺失、累计与单季比较；深/北交所额外独立样本后才能声称覆盖沪深北。
6. **P1-5 私人 PWA 与上线评估（2–3 天）**：概览、财报、公告、报道四栏目，窄屏/桌面阅读与原文跳转；访问拒绝、注销缓存清除、SSRF/提示注入/恶意文档测试、备份恢复及跨地区连通性。只做本地/批准的预览；正式发布、购买和 DNS 另交 PO 批准，不由本计划自动授权。

MVP 覆盖规则：财报拟最近 **3 年年报 + 最近 4 期实际披露的中期/季度报告**；年报不伪造成 Q4，业绩公告与完整报告不同类型。重大公告拟 **90 天**，须有时间窗完整性与分页证明；本次每标的两条列表仅是探针，不满足 90 天完整性验收。报道只显示有权使用的白名单来源，当前可为空并说明接入状态；概览只聚合可核验事实。每公司展示覆盖区间/缺口/最新核验时间，不补造缺项。

## 9. 本次交付与尚未解决项

- 已完成：官方发布包审查和验签、六样本 CLI 实测、SEC 失败探针、政策/IR 路径审查、数据模型/事实规则/安全架构/成本/Phase 1 方案、最小可复现脚本和离线回归测试。
- **未解决且不伪称完成**：腾讯 MCP 接通、后台数据授权/额度/价格；SEC 原文/XBRL 实际通过；HKEX 自动使用/AI 权利；巨潮 API 的授权/可用性及沪深北完整覆盖；金融指标逐项对账与单位问题；媒体实际许可；跨地区受控实测；历史 3 年/4 期/90 天完整性。
- 请求 PM 审核：接受本阶段证据和 CONDITIONAL GO；认可“SEC 先行、腾讯可关闭、权利明确后扩市场”的顺序；核查以下条件是否足够支撑 Phase 1 Issue。**PR 合并权和最终产品验收仍由 PM/PO 流程决定，本次不自动关闭 Issue #1。**

## 10. PM 品牌/UI 审核补充（2026-11-27）

正式名称统一为 **hiwd company**。主站实际页面、明暗主题、字体/字号、颜色、留白、导航、圆角、图标和响应式核验及可复用清单见 [brand-ui.md](brand-ui.md)。主站已成功访问，另有本地桌面和移动端实拍可供对照；不以通用 Apple/金融仪表盘模板替代。历史探针 User-Agent、原始输出及提交记录中的旧名称只作为不可改写的历史测试证据保留。
