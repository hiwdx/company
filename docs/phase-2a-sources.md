# 港股及 A 股信源准入与样本核验

2026-11-27（北京时间）。使用公开查阅页面和官方公开文件的小样本预览。访问结果只描述本次环境。索引摘要、正文预览、产品中的导航和程序接入分别记账。本阶段无港股或 A 股程序化行情、披露 API、批量下载或应用内原文留存。

## 使用范围与成本

| 信源 | 已确认的合法路径 | 自动化、缓存、展示、摘要及 AI | 费用或限制 |
| --- | --- | --- | --- |
| 港交所披露易 | 用户自行阅读。条款第 5 条规定了有限个人使用，包括临时本地副本 | 第 5 条限制未经事先明确书面同意的程序化采集、数据挖掘及 AI 等用途。个人本机浏览或临时保存范围不覆盖产品内缓存、显示、再分发及衍生摘要 | 公共浏览。第 4 条要求链接（含首页）及嵌入均先获港交所书面同意。产品仅指向发行人 IR。港交所条款位于披露易站点页脚的「使用条款」，第 4、5 节可定位。 |
| 港交所 IIS | 交易所正式订阅，提供发行人消息及公告文件。适用时由获许可的信息供应商供给 | 申请与签约后按合同范围接入。产品内展示、缓存期、再分发、摘要、AI 推理及训练需逐项确认，目前未取得 | 官方 Market Data Vendors 价目表列 IIS 再分发费每季 HK$45,000。该条目对应所列供应商类别；本项目适用合同和总成本待确认。 [IIS 服务](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29?sc_lang=en) · [供应商申请](https://www.hkex.com.hk/Services/Market-Data-Services/Real-Time-Data-Services/Data-Licensing/HKEX-IS/Market-Data-Vendor-Licence/Delayed-Data-and_or-IIS/Application-Procedures/Vendor-Application-Procedure-%28for-Delayed-Data-and_or-IIS%29?sc_lang=en) · [官方价目表](https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-%28Hong-Kong%29/Market-Data/Market-Data-Vendors?sc_lang=en) |
| 腾讯及阿里巴巴发行人 IR | 阅读官方报告及公告。阿里巴巴有港交所申报专页和独立财报目录 | 没有核实适用产品的许可。阿里巴巴法律声明限制未经许可的程序监测、复制及传播。腾讯站点条款正文在本次预览不可读 | 公开查阅未要求付费。程序接入和衍生用途的费用未确认。 [腾讯报告](https://www.tencent.com/investors/financial-reports/) · [腾讯网站条款](https://www.tencent.com/index.php/zh-cn/service-agreement.html) · [阿里申报](https://www.alibabagroup.com/zh-HK/ir-filings-hkex) · [阿里法律声明](https://www.alibabagroup.com/zh-HK/disclaimer) |
| 巨潮资讯 | 公开披露页面供阅读。运营方另提供授权数据服务门户 | 门户可识别，未核实正式 API 权限、凭证、披露覆盖、频率、留存、应用展示、摘要及 AI 授权 | 公开查阅未要求付费。授权数据服务价格未核实。 [巨潮公开披露](https://www.cninfo.com.cn/new/commonUrl?url=data%2Fgongkai) · [巨潮数据服务门户](https://webapi.cninfo.com.cn/) |
| 上交所 | 公开查阅。法律声明规定非商业浏览和下载条件，链接指首页 | 不把浏览或下载条款扩大为产品采集或衍生许可。条款限制商业用途、转售及相应获取方式。适用于本项目的自动请求、用户展示、持久缓存、摘要及 AI 权限未核实 | 公开阅读与适用协议的价格分开，当前没有产品授权报价。 [上交所法律声明](https://www.sse.com.cn/home/legal/) |
| 深交所与北交所 | 首选用户访问各交易所首页。没有要求用本轮四样本验证深、北交易所覆盖 | 深交所条款直接预览超时；北交所法律声明有官方索引，正文未独立确认。产品用途均保持待核实 | 未确认覆盖范围、限流及费率。 [深交所法律声明](https://www.szse.cn/application/laws/) · [北交所法律声明](https://www.bseinfo.net/about_neeq/legal_disclaimer.html) |
| 贵州茅台及工商银行发行人 IR | 公开财务报告和公告页面。贵州茅台原文 PDF 可预览。工行 A/H 季报各有发行人公告页 | 未取得产品的自动化、缓存、应用显示、摘要或 AI 许可。工行条款及部分原件预览返回 403 | 公共页面未见公开接口费率。 [茅台公告目录](https://www.moutaichina.com/mtgf/tzzgx/gsgg/index.html) · [工行公告目录](https://www.icbc-ltd.com/page/721853001500491800.html) · [工行网站声明](https://www.icbc-ltd.com/column/1438058319591129099.html) |
| 腾讯自选股 CLI / MCP | Phase 0 CLI 曾在当时授权范围内读出数据和结构。本轮只复核既有证据 | 后续只作为发现候选。CLI 的合约及上游披露授权未确认，MCP 仍未验证，财务来源必须回到正式原文 | 本轮无腾讯接口运行、注册或费用。Phase 0 记录中腾讯柜台币种字段为港币，发行人正式报告用人民币。 [既有 CLI 来源证据见 PR #2](https://github.com/hiwdx/company/pull/2/files) |
| 权威媒体 | 另行验证发行商的产品条款、可复用来源及署名方式 | 正式处理前逐项约定抓取、留存、摘要权、产品呈现和 AI 处理 | 本阶段无接入或费用。 |

## 四样本原文核验矩阵

| 发行人及挂牌 | 法定披露或发行人原件 | 币种、期间和核验位置 | 应用验证 |
| --- | --- | --- | --- |
| 腾讯控股 `00700.HK`，另有 `80700.HK` | [2025 年度报告](https://static.www.tencent.com/uploads/2026/04/09/62d786fcf3d3c8cb7e54791ee95439ac.pdf) · [官方财报目录](https://www.tencent.com/investors/financial-reports/) · [2026 三季度业绩公告](https://www.tencent.com/wp-content/uploads/2026/11/E700_3Qresults.pdf) | 财年 12-31，年度合并报表以人民币百万元列示（每股项目另有单位）。IFRS 年报印刷第 129 页可定位总收入、毛利、经营利润、年度利润和归属母公司股东利润。季度发行人公告区分三个月和九个月，口径不从柜台币种推导。 | 桌面搜索可见 00700 港币柜台、CNY 报告与官方入口 |
| 阿里巴巴 `09988.HK`，另有 `89988.HK` | [发行人港交所申报目录](https://www.alibabagroup.com/zh-HK/ir-filings-hkex) · [年度 20-F 公司原件](https://data.alibabagroup.com/ir_filings/SEC/BABA/000119312526231755/baba-20260331.htm) · [九月季度及中期业绩](https://data.alibabagroup.com/ecms-files/1532295521/e676aff4-e76d-489b-960a-47b9cf36485d/Alibaba%20Group%20Announces%20September%20Quarter%202026%20Results%20and%20Interim%20Results%20for%20the%20Six%20Months%20Ended%20September%2030%2C%202026.pdf) | 财年 03-31。年度样本的 20-F 封面勾选 US GAAP，汇率说明写明人民币为报告币种，美元列供方便阅读。另一份公告区分三个月与六个月。20-F 的申报地属性保留为美国；港股公告和报告版本另记。 | 桌面搜索确认 09988 港币柜台和 2026-03-31，CNY |
| 贵州茅台 `600519.SH` | [2026 年第三季度报告](https://www.moutaichina.com/mtgf/articleFileDir/2026-11/10/ad52ec07cef046609c25ac217defade9.pdf#page=1) · [2025 年年度报告](https://www.moutaichina.com/mtgf/articleFileDir/2026-04/17/1b9fae59825c41bf9a776892a00565f7.pdf) · [公司公告目录](https://www.moutaichina.com/mtgf/tzzgx/gsgg/index.html) | 财年 12-31。年报编制基础为中国企业会计准则。未经审计季报第 1–2 页按人民币元列营业收入、利润总额、归母净利润、经营现金流、总资产。现金流的单季栏目为不适用，九个月可读；总资产是期末余额。第 3 页销售表为万元且包含产品、渠道、地区三种维度。第 5 页资产表和 PDF 文件路径日期各自独立，公告日期以目录为准。 | 390 像素移动视口可见人民币、季报期末与发行人/交易所原文入口 |
| 工商银行 `601398.SH` / `01398.HK` | [A 股第三季度报告公告页](https://www.icbc-ltd.com/page/1289646772725837824.html) · [H 股第三季度报告公告页](https://www.icbc-ltd.com/page/1289647050443288576.html) · [历年财报索引](https://www.icbc-ltd.com/column/1438058343653851145.html) · [既往 H 股原件（人民币、IFRS、A/H 挂牌）](https://www.icbc-ltd.com/SiteCollectionDocuments/ICBC/Resources/ICBCLTD/download/2014/AnnualReport_E20140423.pdf) | 同一法律发行人，两条上市证券。报告币种人民币，财年 12-31。发行人目录将 2026-10-30 的 A/H 季报分列。应按各份原件核对境内准则及 H 股适用准则、客户存款或吸收存款、利息净收入、归母与合并净利润。当前工具读到两份公告页面，A 股原件预览返回 403，本轮未声明两份季报逐行一致或做数值核验。 | 用 A/H 代码分别搜索都进入同一公司，页面展示各自证券及人民币报告 |

港股代码显示保留五位的前导零。交易所使用 MIC，报告币种来自发行人财报，不从交易柜台取值。内部发行人 ID 与 SEC CIK、发行市场、本地证券代码和 ISIN 分开。ISIN 按可核对的同类证券证据填入，未确认的柜台或 A 股条目保持空值。 [腾讯 ISIN 持仓申报](https://www.sec.gov/Archives/edgar/data/81443/000141036826074959/primary_doc.xml) · [阿里 ISIN 持仓申报](https://www.sec.gov/Archives/edgar/data/939934/000175272425097278/xslFormNPORT-P_X01/primary_doc.xml) · [茅台 ISIN 持仓申报](https://www.sec.gov/Archives/edgar/data/933691/000114554925015094/xslFormNPORT-P_X01/primary_doc.xml) · [工商银行 H 股 ISIN 持仓申报](https://www.sec.gov/Archives/edgar/data/1272950/000094040026034619/primary_doc.xml)

正式接入后，每份文件保留发行人、证券标签、申报地、披露类别、语言、法定币种、期间、准则、是否合并、章节、页码及原件指纹。相同日期的多地披露、中文/英文版及不同会计基础分别保存。更正、补充、撤回与经重列的比较期按原始公告建立关系并记录受影响行；原文页、表、行找不到时不发布数字。现阶段链接和目视定位不包含重新分发 PDF 或执行解析。

## 访问失败与下一条可行路径

| 实际观察 | 处置 |
| --- | --- |
| 工行财报入口有官方索引，直接预览及 A 股第三季度 PDF 返回 HTTP 403；独立 A/H 公告页面可读 | 保留官方原文导航和具体公告页证据。记录附件不可核验，停止尝试该被拒路径 |
| 深交所法律声明直接预览超时；北交所法律声明预览未返回可核验正文 | 不凭不完整片段推定任何授权 |
| 巨潮授权门户仅返回标题和页面外壳，腾讯公司服务条款无可读正文 | 记录公开路径与权限未知。没有尝试私有接口或身份替换 |
| 港交所披露易条款限制程序采集，未向数据源执行接入试探 | 可由 PO 评估发行人书面许可或 IIS 授权方案。获批后先验证一份正式报告、五项适用指标、公告目录、页表行追溯及修订版本 |
| 上交所及其他 A 股源未核实可自动化权限 | 可由 PO 评估发行人限定范围的书面许可，或巨潮/交易所正式许可服务。只有获准用途才启用按需读取、限流、缓存及可能的应用内展示 |

每个许可记录应覆盖目的、数据字段、授权地域、期限、限流、留存与删除、可展示文本、派生摘要、模型推理或训练、设备范围、成本和更新流程。无明确许可时维持外链阅读。已有权在本机处理的单份原件可以开展人工导入实验，并在结果上同时标明导入模式和授权范围。
