# hiwd company

从正式披露阅读上市公司的经营和财务。美股原型支持财报核验、中文解读和近 90 天的 SEC 公告目录。港股和 A 股的四个样本提供官方原文入口。目标域名为 `company.hiwd.com`。

在项目根目录用 Python 3.9+ 启动本地阅读器：

```sh
sh scripts/start_local.sh
```

打开 [本地阅读器](http://127.0.0.1:18768/) 搜索证券代码或公司名称。可试 `AAPL`、`TSM`、`00700.HK`、`09988.HK`、`600519.SH`、`601398.SH` 和 `01398.HK`。默认仅监听本机，使用已有的已审阅快照。新发行人研究需要已有的合规 SEC 缓存或经授权的本地访问。

- [v0.1.0-alpha Mac 试用、覆盖范围和反馈](docs/v0.1.0-alpha.md)
- [Phase 0 技术与品牌调研](docs/phase-0.md) · [复现](docs/reproduce.md) · [数据合约](docs/data-contract.md)
- [Phase 2A 市场结论、美股回归和重现步骤](docs/phase-2a.md)
- [港股及 A 股许可与四样本矩阵](docs/phase-2a-sources.md)
- [整合顺序及下一阶段语义核验方案](docs/phase-2a-integration.md)
- [Phase 1C 实测及复现](docs/phase-1c.md)
- [Costco、可口可乐、摩根大通逐项原文对账](docs/phase-1c-reconciliation.md)
- [Phase 1B 历史财报实验](docs/phase-1b.md)
- [hiwd.com UI 核验](docs/brand-ui.md)
