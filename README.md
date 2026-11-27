# hiwd company

面向上市公司公开信息的中文阅读器。当前原型覆盖 Apple 2026 财年 10-K、六项财务指标和两期数据。计划中的目标域名为 `company.hiwd.com`。

使用 Python 3.9+ 和标准库。打开项目根目录，在本机运行：

```sh
python3 -m hiwd_company serve --port 18765
```

浏览器访问 `http://127.0.0.1:18765/`。首次启动会将版本化事实快照写入 `local-results/reader.sqlite`。可切换概览、财报、公告和报道。财报提供金额单位切换、比较期、同比公式和每个数字的原文链接。

- [原文对账、复现与当前覆盖](docs/phase-1.md)
- [hiwd.com UI 实测和设计继承](docs/brand-ui.md)
- [Issue #3 验收范围](https://github.com/hiwdx/company/issues/3)

原型面向本人本地验证。正式站点、账号体系、付费模型、数据轮询均未启用。保持公开仓库无联系人、凭据及完整的上游原文。
