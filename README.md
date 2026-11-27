# hiwd company

hiwd company 是上市公司公开信息阅读器，面向美股、港股、A 股，中文通俗解读，原文可追溯。

不预测股价、不荐股、不评级、不提供买卖建议，不做行情、交易或社区。

当前阶段：Phase 0 数据源可行性验证。产品范围与验收以 [Issue #1](https://github.com/hiwdx/company/issues/1) 为准；技术方案需通过 PR 审核。目标域名 `company.hiwd.com`，尚未部署。

调研入口：[Phase 0 报告](docs/phase-0.md)、[复现说明](docs/reproduce.md)、[候选数据合约](docs/data-contract.md)。

当前结论：**CONDITIONAL GO**。腾讯 CLI 已做六样本只读实测，但权威原文、币种语义及后台使用授权不足；SEC 本环境 403，HKEX 自动化使用存在许可门槛，巨潮授权与跨地区验证未完成。详情见报告，不将探针退出成功视为数据验收通过。
