# hiwd company

从官方披露阅读上市公司的经营和财务。当前本地原型可搜索 Apple、Microsoft、NVIDIA 和台积电，并通过同一页面阅读报告。目标域名为 `company.hiwd.com`。

使用 Python 3.9+，无需安装第三方运行依赖。在项目根目录运行：

```sh
python3 -m hiwd_company serve --port 18766
```

浏览器打开 [本地阅读器](http://127.0.0.1:18766/)。首次启动会将已核验快照写入本地 SQLite。输入公司代码或名称选择发行人，再选择报告。财报支持金额单位、同口径同比和逐项原文链接。

- [Phase 1B 验收记录和复现](docs/phase-1b.md)
- [11 份披露的逐项原文对账](docs/phase-1b-reconciliation.md)
- [hiwd.com UI 核验](docs/brand-ui.md)
- [Phase 1 Apple 实验记录](docs/phase-1.md)
