# 审查员演示环境（第二批交付）

2026-09-29 建立。这是在本地核心栈上跑起来的一套**隔离的合成演示数据集**，供审核员工作流演示与验收使用：看原始信息 → 核对 Agent 建议与依据 → 审批 → 查看结果。它不是第二份进度账本；实际进度只更新 [`tasks/todo.md`](../../tasks/todo.md) 顶部。

- 驱动：[`scripts/reviewer_demo.py`](../../scripts/reviewer_demo.py)（`prepare` / `run` / `status` / `verify` / `stop` / `retire`）
- 演示基础设施：[`infra/compose.reviewer-demo.yaml`](../../infra/compose.reviewer-demo.yaml)，compose 项目名 `resolveflow-review-demo`
- 样本清单：[`samples.json`](samples.json)
- 运行产物（日志、mock 脚本、provider SQLite、进程归属记录）：`tmp/reviewer-demo/`，**不入库**

## 1. 这是什么，不是什么

| 是真实业务服务 | 是 mock / 合成 |
| --- | --- |
| Gateway / case-service / commerce-service（真实 jar，真实 Flyway，真实 MySQL） | Agent 的模型决策：`RESOLVEFLOW_MODEL_MODE=mock` + 每个 run 一份脚本 |
| Agent 服务进程与 AgentScope 2.0.8 生产循环、真实 MCP 工具、真实 PG 策略索引（真实 bge-small-zh 向量） | 订单行、物流故事、客户材料：本驱动直接种入演示库的合成数据 |
| RocketMQ 命令/结果链路、Commerce 退款受理与预留、provider stub 的持久化与故障语义 | 资金：provider stub 的模拟退款，没有真实支付通道 |
| 人工审批（`POST /api/v1/cases/{case_id}/reviews`）与状态机 | 模型"质量"：mock 只证明数据、结构、限制与保存链路 |

订单行与物流行是驱动直接种的（Commerce 没有建单 API，手册允许只向**新演示环境**插入公开合成订单/物流）。工单材料、核验、追问、方案、审批、退款全部走现有鉴权 HTTP API；驱动**不会**用 SQL 设置最终工单状态、授权、退款账本或 Agent 轨迹。

## 2. 隔离

- 独立 compose 项目 `resolveflow-review-demo`、独立命名卷（`resolveflow-review-demo_demo-mysql-data` / `..._demo-postgres-data`）、独立 RocketMQ broker（`listenPort=10912`，`haListenPort=10913`）。
- 全部宿主端口绑定 `127.0.0.1`，且都避开共享 `resolveflow` 项目的端口：

| 角色 | 端口 | 角色 | 端口 |
| --- | --- | --- | --- |
| demo MySQL | 3307 | demo gateway | 8180 |
| demo PostgreSQL | 55433 | demo commerce-service | 8181 |
| demo RocketMQ namesrv | 9877 | demo Agent | 8182 |
| demo RocketMQ broker | 10912 | demo case-service | 8183 |
| desktop web | 5174 | — | — |

- `guard()` 在每次写操作前拒绝：项目名不是 `resolveflow-review-demo`、任一 demo 端口落在共享端口集合、数据集前缀不是 `reviewer-demo`、embedding 快照缺失。
- 数据库语句只经 compose 项目标签校验过的 demo 容器执行；`processes.json` 与 manifest 都记了 environment/project，读到别的环境的文件直接拒绝。
- `verify` 用 `prepare` 时记录的共享库行数做见证，确认演示没有动共享环境。

四个 Java/Python 应用进程以**宿主进程**方式运行（`scripts/reviewer_demo.py` 管理），只连上面这些 demo 端点。这是显式选择：共享项目已经跑着同一批应用容器，本机 Docker 虚拟机约 7.9 GB，再起一份会与"不得打扰"的环境抢内存；隔离真正依赖的是独立的库、broker、provider 文件与策略索引，两种跑法一样。`infra/compose.reviewer-demo.yaml` 顶部写明了这个取舍。

## 3. 可复制命令

工作目录 `E:/Code/Agent+Backend`，PowerShell。

```powershell
# 日常体验入口：启动完整演示栈，并在默认浏览器打开桌面页面
.\demo.ps1

# 查看状态；停止时保留演示数据和Docker卷
.\demo.ps1 status
.\demo.ps1 stop

# 准备/恢复：起基础设施、构建 jar、受控导入政策、建 demo 策略索引、起三个常驻服务
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py prepare

# 只读查看：manifest + 进程归属
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py status

# 只读验收：隔离、样本状态、引用可查、金额/占用不变量、跨商户与凭证
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py verify

# 推进一个样本（每个样本一个订单行；重复执行幂等）
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py run --scenario lost-review

# 停止本驱动启动的进程与 demo compose 项目（不删卷、不清库）
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py stop

# 关闭一次未成形的尝试：对那张工单走产品自己的 REJECT，并把记录移入 retired
agent/.venv/Scripts/python.exe scripts/reviewer_demo.py retire --scenario <name> --reason "<原因>"
```

`--skip-build`（放在子命令前，或 `run` 之后）复用已有 jar。数据集可用 `--dataset` / `--new-dataset reviewer-demo-...` 指定；端口可用 `REVIEWER_DEMO_PORT_<ROLE>` 覆盖，JDK 可用 `REVIEWER_DEMO_JAVA_HOME` 指定（默认会解析 JDK 21，因为本机 `JAVA_HOME` 是 17）。

日常入口使用固定演示前端 `http://127.0.0.1:5174`，代理到 demo gateway `http://127.0.0.1:8180`；它不会改动 5173 的共享前端。浏览器体验使用只读 Agent API，调查循环关闭，因此打开页面不会消费新 run 或调用模型。登录用现有合成账号：`demo-reviewer / demo-pass-1003`（M-1001，审核员）、`demo-reviewer-m2 / demo-pass-2002`（M-1002）。

## 4. 七个样本（`samples.json` 为准）

| scenario | 行号 | 金额(分) | 停留状态 | 授权 | 说明 |
| --- | --- | --- | --- | --- | --- |
| lost-review | 90929041801 | 32900 | PENDING_REVIEW | PENDING_REVIEW | 承运商 LOST、无签收；AGENT 方案 VALIDATED，引用 R-LOST-001，等待人工审批 |
| signed-conflict | 90929043202 | 19800 | PENDING_REVIEW | 无 | 有效签收 + 客户称未收到；AGENT 建议 MANUAL_REVIEW、CONFLICT 分项引用两个真实来源 |
| damage-review | 90929045104 | 45600 | PENDING_REVIEW | 无 | 仅客户描述破损、未核验；AGENT 建议 REQUEST_INFO 并写明缺口，不伪造核验 |
| waiting-info | 90929045003 | 12900 | WAITING_CUSTOMER | 无 | Agent 追问，稳定 `question_id`；再次 `prepare` 不会自动回答 |
| unknown-refund | 90929045105 | 25900 | RECONCILING | CONSUMED | 审批后 provider `REQUEST_TIMEOUT`：原 operation 保持、占用不释放、无重付 |
| success-refund | 90929045206 | 17600 | CLOSED_SUCCESS | CONSUMED | 审批 → 命令过 demo broker → provider SUCCEEDED → 结果回传关单 |
| unknown-recovery | 90929045307 | 8800 | CLOSED_SUCCESS | CONSUMED | 一次性样本：`LOST_RESPONSE` 造成 UNKNOWN，随后同 operation 查询恢复成功 |

`unknown-recovery` 不在六个展示样本里，是手册要求的"另用一次性样本验证恢复"，与展示样本不共享故障开关（故障按 operation_id 装载）。manifest 另有 `retired` 列表，记录三次未成形的尝试（原因与 case_id 都保留，工单本身留在库里且已由产品自己的 REJECT 关闭）。

## 5. 实际验收结果（2026-09-29，`verify`）

全部 PASS：

- 隔离：demo compose 项目自有容器、自有命名卷；demo 端口无一落在共享端口；共享库行数与 `prepare` 时一致（未变动）。
- 样本：七个样本 recorded 与 live 状态一致，各自等于该 scenario 的期望停留状态。
- 来源可查：lost-review / signed-conflict / damage-review 的 `GET /api/v1/cases/{case_id}/investigation` 均 `AVAILABLE`，方案里每条证据引用在 observation_id / source_ref / source_version / content_hash 四项上与已保存记录完全匹配；政策引用与 `GET /internal/v1/policies/{bundle_id}` 服务的规则 hash 相符。
- 金额与占用：UNKNOWN 样本仍是原 operation_id、`line_refund=RESERVED`、`payment_ledger` 已退 0/预留 25900、provider 该键 state=UNKNOWN 且只被呈递 1 次；success-refund 与 unknown-recovery 都是 `paid=refunded`、预留归零、槽位 CONSUMED、provider 同键 SUCCEEDED 且 attempts=1。
- 主体：M-1002 审核员读 M-1001 工单 404；客户读 review-context 403；Agent 进程日志无凭证。
- 幂等：`prepare` 二次执行只 skip 已导入政策、样本 ID 不变、不新增授权；已完成样本再次 `run` 报告"already prepared"且不重建。

参考命令（第二批手册指定）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_openapi.py agent/tests/unit/test_e2e_driver_process_ownership.py agent/tests/unit/test_reviewer_demo_driver.py -q
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_deployment_factory.py agent/tests/integration/test_resident_investigation.py agent/tests/integration/test_reviewer_sources.py -q
```

实测：第一条 178 passed（含新增 16 条驱动边界测试）；第二条 25 passed；全量 `agent/tests` 1175 passed / 5 failed / 12 skipped。

## 6. 环境限制与已知问题

1. **committed replay golden 已过期（5 个失败，非本批引入）**：`agent/tests/integration/test_replay_golden.py::test_committed_golden_pack[*]` 在 HEAD 上同样失败（本批改动前后都是 5 个）。原因是 `evals/replay/golden/**` 里提交的 pack 记录着已过期的 deadline，且 `prompt_hash`/`tool_schema_hash`/`code_revision` 来自更早的代码版本（当时的 system prompt 还没有 review_findings 段）。重新生成会改写 replay 证据，属于第四批轨迹回放的范围，本批只报告不改写。
2. **测试 fixture 的过期 deadline 已修**：`agent/tests/integration` 里 5 个模块硬编码 `deadline_at = 2026-09-28T05:00:00Z`，该时刻过后所有经过 worker 的测试都以 `BUDGET_DEADLINE` 失败。本批改为 `tests.integration.future_deadline()`（同时修好了 5 个 `test_golden_trajectory`）。
3. **第二个演示商家的账号与政策不一致（既有问题）**：`DemoAccounts` 里 `demo-customer-m2`/`demo-reviewer-m2` 属于 **M-1002**，而 `fixtures/policies/bundles/policy-damage-*.yaml` 属于 **M-2002**。结果是第二个商家没有任何政策 bundle，damage bundle 也没有对应账号。因此 `damage-review` 样本落在 M-1001，用"该商家钉住政策里没有破损规则"的事实如实呈现（方案不引用任何政策、`missing_evidence` 写明缺口），没有借用别的商家规则来凑引用。
4. **Agent 每个 scenario 重启一次**：`RESOLVEFLOW_MOCK_SCRIPT` 在装配期读入，一份脚本只能服务一个 run；驱动在**建单之前**停掉上一个 Agent，避免旧脚本应答新 run。默认脚本在 `tmp/`，不入库。
5. **一次中断的 run 不可恢复**：若 Agent 在调查中途被中断，该 run 恢复时第一次 provider 请求的重试额度已用尽，只能以 `MODEL_RETRY_EXHAUSTED` 失败。`retire` 因此会先走 `POST /internal/v1/runs/{run_id}/cancel`，再对工单 REJECT，尽量不留 RUNNING 残留。
6. **进程归属按端口判定**：Windows 上 `agent/.venv/Scripts/python.exe` 是启动器，真正持有套接字的是它的子进程。驱动同时记录两个 PID 并用 `taskkill /F /T` 终止进程树；端口已被非本驱动的进程占用时**拒绝启动**而不是静默换端口。
7. **本机 Java 默认是 17**：驱动会解析 JDK 21（`~/.jdks`、Program Files、最后才是 `JAVA_HOME`），否则 Maven enforcer 会以"jars did not build"的形式报错。
8. **未调用任何收费模型**：全程 `RESOLVEFLOW_MODEL_MODE=mock`，进程环境里显式移除了 `RESOLVEFLOW_MODEL_ENDPOINT/ID/API_KEY/PROVIDER`。真实模型质量验证仍未授权、未运行。

## 7. 一键浏览器入口验证（2026-09-29）

根目录新增`demo.ps1`，它复用本驱动的隔离、端口冲突和进程归属机制。默认`start`会准备后端、启动关闭调查循环的只读Agent API、启动固定5174端口的Vite前端并打开默认浏览器；`status`和`stop`由同一进程账本负责。只读Agent进程会移除所有live模型环境变量和mock脚本，因此页面浏览只能读取已持久化结果。

实际验证：

```powershell
agent/.venv/Scripts/python.exe -m py_compile scripts/reviewer_demo.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_reviewer_demo_driver.py -q --basetemp .pytest-tmp/demo-start-unit
pnpm --dir web test
pnpm --dir web build
.\demo.ps1 -NoBrowser
.\demo.ps1 status
.\demo.ps1 stop
.\demo.ps1 -SkipBuild -NoBrowser
```

结果为驱动单测20 passed、前端68 passed、前端构建通过。运行态验证覆盖：热启动复用、重复启动幂等、5174经Vite代理登录为REVIEWER并读取3条待审工单、默认命令成功唤起系统浏览器、停止五个宿主进程及演示compose且保留数据、停止后的完整恢复路径，以及服务停止时`status`不访问数据库并显示offline。`-SkipBuild`冷启动依次通过MySQL/PG、RocketMQ、政策导入、Case/Commerce/Gateway、政策索引、只读Agent和桌面前端健康检查；Java源码未变，本次未重复Maven测试。
