# Jev 客服回答辅助检查

2026-11-02。用户选择先完成可演示的实际接入，再按效果决定简历表达；不以研究规模评测或预设提升比例阻塞。保持现有 AgentScope 主循环、流式回答、Java 权限及退款职责。

## 采用方式

- TypeSafe 官方 `POST https://api.typesafe.ai/v1/systemone`，固定 `jev-1.14.0`；使用现有 httpx，不改依赖锁。
- 三分类 `supported / contradicted / insufficient_evidence`，只作回答与本轮材料一致性辅助检查。
- 模型置信度不等于正确率，更不等于退款授权；不自动拦截或改写买家回答。
- `.env` 只存本机密钥，Git 已忽略；服务不会在 import 时自动读密钥，启动入口显式加载允许的 Jev 配置，进程环境优先。

## 第一步：客户端与配置

文件：`agent/src/resolveflow/support/jev.py`、`agent/tests/unit/test_jev.py`。

实际命令：

```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_jev.py -q
.\agent\.venv\Scripts\python.exe -m ruff check agent/src/resolveflow/support/jev.py agent/tests/unit/test_jev.py
.\agent\.venv\Scripts\python.exe -m mypy --config-file agent/pyproject.toml agent/src/resolveflow/support/jev.py
```

15 项单元通过、Ruff通过；首次先红为模块不存在的收集失败。覆盖精确模型/官方端点、密钥不进配置快照、环境优先级、保留冲突/失败材料、实际 usage、HTTP302/401/402/429/500 不重试、不跟随重定向、不保存敏感错误正文、非法响应与超时不冒充语义结果。

本步尚未接入客服运行，不宣称业务完成或质量提升；本步无付费调用。先前单条官方连通验证不作为质量评测。

## 第二步：客服运行与持久记录

文件：`support/service.py`、`support/jev_audit.py`、追加迁移 `014_support_jev_audit.sql` 和 `tests/integration/test_jev_runtime.py`。

成功回答后最多一次 Jev 请求，不编辑回答、摘要或业务动作；本轮全部已读 observations（包括失败记录）进入检查，不把仅挑出的引用当全部证据。输入过大明确跳过，不裁掉例外后继续检查。配置及源码进入 manifest；独立 `kind=jev` 区分生成模型调用和判断调用，不修改跨服务响应契约。

沿用同一模型次数/输入/输出预算与 deadline，在网络前持久预占，网络不持数据库事务；响应及 usage 经 fence 保存。已完成检查复用；STARTED 且未保存的响应保持 UNKNOWN、不自动重付。HTTP错误/超时保存 ERROR 和估算预占，不假装检查通过；余额不足等模型故障不影响原答案，数据库/fence 错误继续拒绝旧执行者写入。

验证使用独立本机 Docker 容器 `resolveflow-jev-check-20261102` 的 PG55439，没有使用或清理项目业务库/卷。

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55439/agent_db'
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_jev.py agent/tests/integration/test_jev_runtime.py agent/tests/integration/test_support_store.py agent/tests/integration/test_support_stream_runtime.py -q
```

第一轮35通过（15客户端+9新集成+11既有恢复/流式）；新增预算耗尽/完整大材料跳过两项后，新集成11通过。Ruff定向通过。首次PG未运行9跳过不作通过；使用隔离PG后9项先红（尚无接线），实现后转绿；首次Ruff三行长度已修复。既有 Starlette/AnyIO 弃用 warning 保留。暂未真实 Jev 小测，也未宣称质量提升。

接口来源：[System One](https://docs.typesafe.ai/api/system-one)、[Choice](https://docs.typesafe.ai/primitives/choice)、[模型](https://docs.typesafe.ai/models)。

定向 mypy `--follow-imports=skip` 检查3个本批源码通过；完整导入检查长时间无结果，停止本轮所属进程，未计为通过。首次定向检查暴露导入跳过后的Any返回，补显式边界cast后通过，不代表全项目类型检查。

第二步提交前差异检查曾因Windows写入CRLF报逐行尾空白；串行命令未在失败处停止，7e57ccd2已提交推送。随后立即统一本步新增测试/报告为LF，单独修复提交，不重写历史；后续提交明确先检查退出码。

## 第三步：启动、查看及真实小测

正式本机 `start.ps1` → `scripts/project_runtime.py start` 显式加载根 `.env` 的 Jev 白名单配置，原进程环境优先，配置校验先于进程启动。本机已设置 `RESOLVEFLOW_JEV_ENABLED=1`；固定模型1.14、默认超时4秒。改为0可关闭。本批未重启正式项目，下一次普通启动会读取；已有服务切换配置须正常停启。

检查位于最后回答生成后、运行持久完成前；不改变增量输出，但最终完成增加一次检查耗时（默认超时4秒，另受原deadline/预算限制）。结论只进入运行日志和PG；没有新增平台网页面板，没有自动拦截、重写或纠错。

查看正式运行记录（沿用 `RESOLVEFLOW_AGENT_DB`，只读、零推理）：

```powershell
.\agent\.venv\Scripts\python.exe scripts/jev_check.py --run-id <咨询run_id>
```

返回 `kind=jev` 的请求、响应、hash、usage、耗时和状态；ERROR/SKIPPED/STARTED均不是语义通过。CLI初次重定向因系统编码导致UTF-8复读失败，固定标准输出编码后，查询结果与原保存响应完全一致。

真实小测命令：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55439/agent_db'
.\agent\.venv\Scripts\python.exe scripts/jev_check.py --smoke --live --output tmp/jev-smoke-20261102/results.json
```

必须显式 `--live`；结果文件存在则拒绝覆盖重跑。固定12题、预期先写，来源 `agent/tests/fixtures/jev-smoke-v1.json`，合成中文而非真实客户。经过生产SupportRuntime、AgentScope和隔离PG；主回答模型是脚本mock，来源是合成内存适配，仅Jev为真实官方调用。本批没有DeepSeek请求、购物/退款/审批或项目业务写入。

| 结果 | 实测 |
| --- | --- |
| Jev完成/与预期一致 | 12/12，5支持、4矛盾、3缺证 |
| 原回答保持 | 12/12 |
| 输入token | 11,306 |
| 耗时中位数/最大 | 609.5ms / 1031ms |
| 按公开输入单价估算 | $0.000474852，未查询账户实际扣款 |

公开逐项原响应见[小测结果](jev-smoke-20261102.json)；完整请求及fixture hash保存在 `tmp/jev-smoke-20261102/results.json`。测试schema `jev_smoke_671c2deb76ad` 与public隔离，所属容器停机保留数据。简单构造题12/12只证明基本用途可用，不是实际客服准确率100%、质量提升或降本结论。

## 最终验证与未运行项

- Jev客户端、启动、内部HTTP分派、完整应用指南、预算、故障、恢复及旧fence，加原恢复/流式/启动回归共57过，无跳过。内部HTTP契约保持，结论不塞进买家回答。
- Ruff本批7文件通过；mypy四源码 `--follow-imports=skip` 通过，不代表全项目类型检查。原完整导入检查未完成。
- 扩大所有 `test_support*.py` 加本批用例，首次690项672过/18失败。本批HTTP测试误写导入路径 `resolveflow.mcp.auth`，改为现有 `api.identity` 后转绿；其余17项为旧指南版本、旧编排脚本/调用次数与旧页面指引断言。
- 独立Python进程内存加载 `git show 6909111c:agent/src/resolveflow/support/service.py`，其余源码不变，复核11个相关文件：同17个失败全部重现（另4过）。这是原运行实现定位复核，不是完整基线checkout。未改旧断言，不宣称全套通过。原日志/XML位于 `tmp/jev-smoke-20261102/`：regression、baseline及focused。
- 客户端15先红、集成9先红、PG未启动9跳过、Ruff/类型边界/CRLF/CLI编码失败保留。报告追加曾有补丁标题定位失败，未误改Harness规格。
- 未做浏览器三角色整链、真实主模型质量对照、自动纠错或整套退款新测；不沿用历史通过。原4历史改动保持。
