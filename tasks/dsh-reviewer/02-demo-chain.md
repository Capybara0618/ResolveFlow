# 第二批：稳定样本和mock整链路

先读[总约束](README.md)。目标：固定样本可恢复、真实服务链路可演示；本批只允许显式mock模型。

## 1. 已查明的入口与缺口

| 入口 | 现状与使用限制 |
| --- | --- |
| `scripts/seed_review_showcase.py` | 已有HUMAN方案样本和 `--resume-case`；不能改称Agent样本 |
| `scripts/e2e_resident_refund.py` | 真实Java/MCP/PG/MQ/provider接线，mock模型；会启动全局扫描，不可原样对共享库执行 |
| `scripts/e2e_refund_chain.py` | 工单行种子、进程工具、8083/8081端口；helper含共享环境假设，调用前参数化 |
| `scripts/e2e_transport_refund.py` | 基础DB/进程/报告辅助，先检查硬编码容器及DSN |
| `agent/src/resolveflow/runtime/factory.py` | 显式mode；mock需要脚本，生产循环不改 |
| `agent/src/resolveflow/provider_stub/`、`fixtures/provider/README.md` | 持久provider与故障注入；UNKNOWN采用已有机制 |
| `infra/compose.yaml`、Java两服务 `application.yml` | 原环境名resolveflow；DB/MQ/provider必须成套隔离 |

## 2. 子步A：先消除5个已知契约失败

先运行总手册的两文件pytest命令。上批结果153 passed/5 failed只作历史定位，不复制为本次结果。

1. `docs/core-contracts.md` 第3节表缺Case的 `GET /api/v1/cases/{case_id}/review-context`、`POST /api/v1/cases/{case_id}/review-actions`、`GET /api/v1/cases/{case_id}/investigation`，以及Agent的 `GET /internal/v1/runs/{run_id}/review-sources`。核对Controller/API实际实现后补入主表；后文说明保留。
2. `agent/tests/unit/test_contracts_core_routes.py` 的 `EXPECTED_ROUTE_COUNTS` 当前是Case18、Commerce5、Agent5。补表并实际数路由后应为21/5/6；若实际不同先解释差异，不能盲改常量。
3. `contracts/core/openapi-agent.yaml` review-sources和 `contracts/core/openapi-case.yaml` investigation描述缺authority，补指向 `docs/core-contracts.md` 对应规范。再检查另两条已有新增路由是否也缺，保持所有operation的检验。
4. review/cases已有status/q筛选，旧测试只认Cursor/Limit。按真实Controller/OpenAPI更新第3节队列表和测试：允许status/q/Cursor/Limit，仍禁止客户端传merchant_id/customer_id决定主体；保留400/401/403、游标、状态/搜索合法性要求。补非法参数的服务端用例如已有则复用。
5. 不删除“实际路由与主表完全一致”或authority测试。修复后两文件全部通过，记录实际计数。

本子步允许修改上述4个契约/测试文件及必要的队列测试，不改资金逻辑。

## 3. 子步B：建立隔离的演示运行环境

选定方案：复用现有镜像、Compose服务定义与锁，新增演示专用Compose配置/驱动，使用固定项目名 `resolveflow-review-demo`。这是本地现有角色的隔离运行，不是新业务服务。不得重用现有resolveflow项目的DB卷、PG库、provider SQLite或MQ消费者状态。

执行顺序：

1. 清点现有端口/容器；生成演示配置，所有宿主端口绑定127.0.0.1且可配置，避开现有8080/5173、3306、55432和broker端口。不通过停止用户现有容器腾端口。
2. 新配置使用项目私有网络、卷和broker，Java/Agent在同网连接。MQ broker advertised address设置为演示网络内可达服务名，不能让容器连接127.0.0.1指向自身。禁止仅改consumer group却共用原topic来“隔离”。
3. 复用现有初始化与Flyway；不复制业务库快照。将公开合成身份、订单种子、政策导入及索引初始化到演示库。政策索引必须归属于该环境/manifest，不能读原环境索引后伪称已初始化。
4. Agent子进程环境明确设置 `RESOLVEFLOW_MODEL_MODE=mock`、`RESOLVEFLOW_MOCK_SCRIPT`、`RESOLVEFLOW_INVESTIGATION_ENABLED`、本环境Case/Commerce地址、`RESOLVEFLOW_AGENT_DB` 和provider路径。移除继承的live endpoint/key配置；缺mock脚本直接失败。配置和日志不能打印密钥。
5. `RESOLVEFLOW_POLICY_INDEX=1` 只有索引准备成功才启用。沿用本地已缓存embedding；不可达/缺缓存记录环境阻塞，不能用stub冒充真实检索。单测仍可显式用stub。
6. 固定项目与卷可复用；重复启动不重置。清理只停止本次创建且仍匹配PID/启动标识的进程，不删除数据。资源不足就记录需要的资源，不自动停其他项目。
7. Gateway连到演示Case；前端支持显式演示代理配置/独立端口，通过现有Vite配置扩展（先核对文件），并显示“合成数据 / mock / 模拟退款”。不要悄悄更改现有5173所连后端。

建议新增 `infra/compose.reviewer-demo.yaml` 与 `scripts/reviewer_demo.py`。这是待实现接口，不是目前已有命令。脚本先实现 `--help`，子命令约定：`prepare`准备/恢复；`verify`检查；`run --scenario <name>`推进指定样本；`status`只读；`stop`只停自有服务。端口/输出目录可配置，所有写操作在启动时验证项目和环境身份，发现指向共享库立即拒绝。

运行前用 `docker compose ... config` 检查合并结果的project/volumes/ports/network。不要先运行旧e2e脚本再修隔离。

## 4. 子步C：样本清单、恢复和六类场景

新增一个不含凭证的样本manifest，例如 `reports/reviewer-demo/samples.json`。内容保存schema_version、dataset_id、environment标识、scenario、case_id/line_id/run_id/input_revision、proposal_origin/model_mode、实际状态、生成时间和验证时间；运行产物先放忽略目录，经过脱敏仅提交稳定ID与说明。不存在的ID不能先填成样本。

每个scenario拥有独立新订单行；已有7001等基础fixture只用于读结构，不能批准其遗留授权。Commerce缺创建订单API，允许种子helper仅向新演示环境插入公开合成订单/物流；Case材料、核验、追问、方案、审批必须走现有鉴权API。不得SQL直接设置最终case状态、授权、退款账本或Agent轨迹。

manifest在每个不可逆业务步骤后原子保存。幂等键由dataset/scenario/步骤稳定生成；重跑先读状态和ID，不另建工单、不自动推进待审样本。若样本已被人工操作，报告“状态已变化”；显式新dataset才生成替代样本，不把原记录改回演示状态。

| scenario | 数据与动作 | 停留状态与必须可见的内容 |
| --- | --- | --- |
| lost-review | 新行，物流确认LOST、无有效签收；mock通过工具/检索实际读取并PROPOSE | 停在有效待审授权，不自动批准；有引用和review_findings |
| signed-conflict | 客户未收到，物流有效签收 | 补证或转人工；矛盾来自两个真实保存的来源，不能按丢失直接执行退款 |
| damage-review | 仅客户描述损坏，尚无人核验 | 材料显示未核验，缺口明确；不造“真实性已验证” |
| waiting-info | 从独立工单走REQUEST_INFO | WAITING_CUSTOMER；保存稳定question_id；再次prepare不自动回答 |
| unknown-refund | 合法方案→人工审批→provider故障产生UNKNOWN | 原operation/provider ID和占用保持；明确待确认，无重付按钮 |
| success-refund | 独立合法方案→人工审批→实际模拟退款 | CLOSED_SUCCESS且provider、Commerce金额/事件与Case结果一致 |

mock输出使用当前ABI；`review_findings` 最多8项，kind只用FACT/INFERENCE/CONFLICT、引用真实observation IDs。不能让mock生成任意UUID/hash作为依据。预读帮助构造脚本时须与该run实际持久记录交叉验证，不得只有preflight结果却没有Agent调查记录。脚本逐run/逐scenario绑定，禁止一套固定丢失脚本处理所有run。可以用工厂注入的测试客户端，不能往生产循环添加业务if/固定工具序列。

先保留六个用于展示的样本，再用独立临时样本验证等待补证→正确question_id答复→新run→新方案；不能为了测试推进掉唯一waiting-info展示样本。

UNKNOWN以既有provider故障模式及Commerce reconciliation能力实现；核对 `fixtures/provider/README.md` 和 `RefundChainSystemTest`。必须记录触发方式、同operation重放/查询前后的provider支付记录及预留，不能仅截图“UNKNOWN”。可保留一个UNKNOWN展示样本，另一个一次性样本验证恢复，不让两者竞争故障开关。

## 5. 集中验收与交付

| 验收 | 明确通过条件 |
| --- | --- |
| 环境隔离 | 演示进程只连接专用DB/PG/provider/MQ；原环境抽查样本、队列状态未变化 |
| 幂等恢复 | prepare执行两次样本IDs不变、无新增授权/支付；中途退出后续跑不重复效果 |
| 真实链路 | 新工单的AgentScope mock→MCP→检索→持久记录→Java回调复核→人工审批→MQ→provider→结果回传均有同case/run/operation证据 |
| 来源可查 | 对应样本GET investigation的正文与引用完整匹配，mock来源明确，不能仅人工方案顶替 |
| UNKNOWN | 原ID保持、无第二次成功、占用未释放；验证期间无换ID重付 |
| 凭证/归属 | 跨商户访问404、没有把token/连接口令写入报告 |

现有定向命令：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_openapi.py agent/tests/unit/test_e2e_driver_process_ownership.py -q
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_deployment_factory.py agent/tests/integration/test_resident_investigation.py agent/tests/integration/test_reviewer_sources.py -q
```

给新驱动补少量边界测试：拒绝共享环境/live、重复prepare、进程归属；新增测试路径由实现者写进报告。真实链路运行用新驱动实际完成后的help/命令，不复制未支持参数。若改Java调度，重跑第一批对应 `AgentRunDispatchApiTest,ReviewDecisionApiTest,AuthorizationConsumptionApiTest`；没改不机械重跑全部83项。

交付 `reports/reviewer-demo/README.md`、脱敏样本manifest、可复制启动/续跑/只读查看/停止命令、实际服务URL和环境限制。报告区分真实业务服务、mock决策、合成订单、模拟支付、embedding真实/替身。全部必要验收过后更新todo并提交；否则该批保持未完成。
