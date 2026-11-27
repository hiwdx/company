# Phase 0 复现说明

范围：一次性的低频、只读可行性探针。请先审阅 [调研报告](phase-0.md) 的权利与失败边界，再在获准环境执行。不要把复现脚本直接接成无人值守生产服务。没有通过登录、付费或使用权审批的步骤不自动进行。

## 环境与离线检查

Python >=3.9、curl。本次实际运行于 macOS arm64；Linux 下载分支未执行验证。无需 npm、模型 key、腾讯账号或项目依赖安装。

```sh
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=local-results/pycache python3 -m py_compile scripts/probe.py scripts/prepare_westock.py
```

`tests/fixtures/cli-schema.txt` 为合成数据；测试覆盖“失败:0”误判、多行 Markdown、禁止数值持久化、带签名/凭据 URL 不公开、固定 SEC 主机范围及遇拒绝即停止。通过这些测试不代表数据源成功。

## 获取固定腾讯 CLI

```sh
python3 scripts/prepare_westock.py
local-results/bin/westock --version
```

下载器只访问已核实的 SkillHub API、腾讯 COS 发布存储与 stockbuddy.qq.com，最多 3 次重定向、每次最长 60 秒、64 MiB 上限；验证内容指纹、包内版本、固定 SHA256 清单及平台二进制。不会修改 shell profile 或全局安装，不会运行第三方安装脚本。文件已存在则停止，不覆盖；内容/来源不匹配时停止审查，不能去掉校验重试。

实际包来自以下公开路径：

```text
https://api.skillhub.cn/api/v1/download?slug=westock-data&namespace=tencent-adm
https://stockbuddy.qq.com/release/skillhub/cli/v0.0.2/SHA256.txt
https://stockbuddy.qq.com/release/skillhub/cli/v0.0.2/westock-darwin-arm64
```

锁定的是已通过 SkillHub 官方工具本地验签的 **内容指纹**。下载器不重新声称验证发布者身份，溯源见 `docs/evidence/westock-provenance.json`。需要重新做平台验签时，按 [官方验签指南](https://skillhub.cn/docs/verify-signature?namespace=tencent-adm&slug=westock-data&version=1.0.7) 获取工具及公钥，在工作目录审阅后执行：

```sh
python3 skills_store_cli.py verify '@tencent-adm/westock-data@1.0.7' --zip westock.zip --json
```

上面的 `skills_store_cli.py` 是另行审阅取得的官方工具，**不在本仓库内**，不是随 clone 自动可用的命令。本次实际返回 `ok=true`、`verify_mode=local`、`content_hash_match=true`。内容校验不等于服务/数据授权。

## 执行腾讯探针

```sh
python3 scripts/probe.py westock --binary local-results/bin/westock --output local-results/westock-run.json
```

默认包含 6 样本的 18 次中/英/代码搜索，再按市场各批量取 profile、4 期三表、每标的 2 条财务类公告和 1 条详情。单条命令超时 45 秒，命令之间等待 1.1 秒，无自动重试；这是研究主动节流，不是供应商公布的额度。**运行前如已发生明确配额/授权拒绝，先解决该条件，不应持续运行。**

单独复核字段、链接与普通公告列表：

```sh
python3 scripts/probe.py westock --stage followup --binary local-results/bin/westock --output local-results/westock-followup.json
```

诊断保存响应哈希、字段、身份/日期/公开链接等少量元数据，丢弃原始正文和财务数值；stderr 只保存哈希，避免登录 URL/token 入日志。未知格式、错误标记、无表格分别保留，必须人工判读；普通公告的多行标题仍可能不完整。详情中的 HTTP 镜像只记录，不跟随、不转换成官方 URL。

当前脚本检测 CLI stdout/stderr 的明确登录、授权或限流提示后停止后续调用；不过 CLI 没提供稳定机器错误合约，不能保证识别全部未知格式，操作者仍应监控并在新拒绝信号出现时中止。生产需要结构化错误合约，本脚本不能用作后台批采集器。已留存的现场日志来自加入此额外保护之前的版本，未出现这些明确拒绝；新增停止逻辑以离线回归验证，未主动触发上游限流。

## SEC 探针

SEC 允许符合政策的脚本访问，须使用真实项目名称及联系信息的 User-Agent。以下 `<项目名和真实联系人>` 是需要操作者填写的参数，不是可用凭据：

```sh
SEC_USER_AGENT='<项目名和真实联系人>' python3 scripts/probe.py sec --output local-results/sec-run.json
```

本次实际 User-Agent 已记录在 SEC 证据中，为 CompanyPhase0 项目与 GitHub Issue 联系地址；没有伪造浏览器身份。本环境已出现两个主机 403，**应先通过 SEC 官方支持/合规访问排查，不应为取得 200 轮换 UA、IP 或代理**。

脚本只请求明确列出的 SEC 主机，不跟随重定向，无 Cookie/凭据，无重试。www.sec.gov 拒绝后不再请求该主机原文；data.sec.gov 拒绝后不再请求该主机其余公司/XBRL。成功路径会尝试 submissions、companyfacts 及一份原文，但本次这些成功分支没有通过现场验收。CIK 样本值是探针输入，SEC 返回前不能当成已核验身份映射。

## 结果判读与发布

进程退出码 0 只表示探针写出诊断，不表示数据源通过。逐项检查 HTTP 状态、parse_status、summary、原文权威性和许可。HTTP 200 HTML/错误页、部分失败、访问限制不能当正常数据。

默认使用 `local-results/`，已被 git 忽略；输出文件存在则在联网前拒绝覆盖，保留每次结果。不要将上游原始全文、批量财务表、API key、登录 URL、授权头、Cookie 或签名链接提交。要提交新的证据，人工审阅脱敏后放 `docs/evidence/`；不要覆盖旧运行的日期与哈希。当前仓库没有真实全文 fixtures。

HKEXnews、未授权巨潮 API、交易所私有查询和媒体采集没有可运行抓取脚本，这是明确的政策/授权边界。报告所列 IR/条款观察可以打开相应官方页面人工复核；不把人工阅读或 web 索引记录冒充正式数据 API 的成功。
