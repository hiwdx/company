# hiwd company

从正式披露阅读上市公司的经营和财务。搜索证券代码或 SEC 公司名称，按需发现报告、核验财务事实、生成中文解读，并查看近 90 天的官方公告。目标域名为 `company.hiwd.com`。

在项目根目录使用 Python 3.9+ 运行本地原型：

```sh
python3 -m hiwd_company serve --port 18767
```

打开 [本地阅读器](http://127.0.0.1:18767/)。默认可浏览已有的已审阅快照。如果需要查询新发行人，按验收文档配置获授权的 SEC 联系方式和本地网络。

- [Phase 1C 实测及复现](docs/phase-1c.md)
- [Costco、可口可乐、摩根大通逐项原文对账](docs/phase-1c-reconciliation.md)
- [Phase 1B 历史财报实验](docs/phase-1b.md)
- [hiwd.com UI 核验](docs/brand-ui.md)
