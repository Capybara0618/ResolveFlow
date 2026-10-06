# Docker 恢复后的 RAG 业务部署验收

2026-10-06，用户恢复 Docker 后继续完成上一批的原业务部署缺口。沿用工程 `f0048a8` 的生产源码和现有数据卷；新增内容仅为验收驱动、隔离测试及报告，没有再次修改 Agent 提示、检索算法、预算、Gold，也没有重跑 32 例收费对照。前一批语义与整体对照见 [原报告](../rag-delivery/README.md)。

## 当前可体验的链路

`start.ps1 -NoBrowser` 已重建并启动 Gateway、Case、Commerce、真实调查 Agent 和网页，以及原 MySQL/PostgreSQL/RocketMQ。`start.ps1 -SkipBuild -NoBrowser` 再次启动复用健康进程，所有九项状态通过。浏览器地址 http://127.0.0.1:5174/#/shop ，买家 `buyer01`、商家 `admin01`，密码均为 `123456`。这仍是本地模拟交易系统。

新增一笔独立合成购买，从正式 HTTP 入口完成：购买 → 模拟付款 → 申请取消未发货商品 → Java 派发 → 常驻真实 DeepSeek worker → MCP 读取订单上下文 → 模型生成政策 query → 本地 BGE 子块召回 → 完整政策引用 → Harness 校验 → 建议回调 → 商家账号模拟人工审批 → Java 退款执行 → 买家完成状态。未给模型指定工具顺序、query 或终局。

- 工单 `12b357d0-a69f-4aaa-9b7b-25bcf80e07ed`，run `3d0289ae-41b5-57c1-997b-314a78ffae2f`。
- 实际模型 `deepseek-flash`，3 次调用全部 SAVED/live；provider 输入 3,673、输出 430 token，均为真实计数。另一个评测脚本的 usage ledger 不代表常驻业务 worker 的这些调用。
- 模型 query 为“未发货 取消订单 退款 条件”，实际工具记录为 `get_order_context`、`search_policy`。引用 Java 原规则 `R-UNSHIPPED-001 / c-01 / 2026.10`，run manifest 锁定当前精确 generation。读取订单上下文已包含真实未发货投影，本例没有强制再调用物流工具。
- STARTED/PROPOSAL 两回调均 DELIVERED/ACCEPTED；建议 REFUND。329 元模拟退款 SUCCEEDED，同行成功操作只有 1 个，预留归零，买家 CLOSED_SUCCESS。
- 25 次已记录 HTTP 检查包含恢复时重复读取和重试拦截，不能称 25 个独立场景。覆盖其他买家/商家读取 404、买家/平台审批 403、旧协作版本 409、重复已消费审批 409。登录调用未计入这 25 次。

结果见 [机器证据](verification.json)。审批由验收驱动使用商家身份执行，不是模型自动审批，也不是用户亲自验收。

## 数据保留与索引部署

启动前没有历史待处理 run：4 个均 COMPLETED，原模型调用 15 个。原 4 工单、4 负责人、4 政策 pin、3 政策、3 授权、3 退款操作、4 账本和 4 run 的核对字段均保持；字段范围使用 `product_flow_acceptance.baseline_state`，不是所有数据库列的完整备份。新增后模型调用共 18 个，没有其他收费调查。

原三商家政策导入全部 skipped/same hash。追加 012 迁移后，每店新 READY generation 均为 token-children-v1、6 个检索子块。旧 24 generation 行及其原字段身份/lineage 保留，新增后 27 行。既有受控索引入口的 `--replace` 将三个旧 READY 改为 BUILDING；这是退役状态，不是删除。旧 run 不重新执行、不切换 manifest；退役 generation 不再作为可恢复 READY 索引。重复正式启动未再次换代。不能将本次升级说成旧调查无条件兼容恢复。

真实 Docker PG 为 16.15，fsync/synchronous_commit 均 on。BGE 长条款隔离探针仍得到 1501 token → 4 个子块、最大 380 token，完整父条款及末尾例外返回、权威 hash 正确、超长 query 拒绝；临时 schema 正常清理。见 [探针](native-probe.json)。tokenizer 对全文测量时打印 1501 > 512 的长度提示，实际 embedding 只处理合规子块，没有把超长全文送入 encoder。这是工程完整性检查，不是语义准确率。

## 实际命令与验证边界

```powershell
docker compose -f infra/compose.reviewer-demo.yaml up -d
# 首次验收：在启用 worker 前保存基线；已有基线时拒绝覆盖。
agent/.venv/Scripts/python.exe scripts/rag_deployment_acceptance.py snapshot
.\start.ps1 -NoBrowser
agent/.venv/Scripts/python.exe scripts/rag_deployment_acceptance.py exercise
.\start.ps1 -SkipBuild -NoBrowser

$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_policy_children.py agent/tests/integration/test_policy_index.py agent/tests/unit/test_policy_segments.py agent/tests/unit/test_policy_generation_pin.py -q
$env:RESOLVEFLOW_EMBEDDING_PATH="$PWD/tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"
agent/.venv/Scripts/python.exe scripts/policy_native_probe.py --output tmp/rag-docker-delivery/native-probe.json
```

首次基线由 `tmp/rag-docker-baseline.py` 保存，内容与正式驱动 snapshot 相同；随后加入可复现入口。上述 exercise 会保存请求幂等键，后续调用沿用同一订单/工单，不创建新样本，不重跑已完成模型。首次脚本在退款成功后因把 SHOP 前缀订单行当 UUID 而停止；修正为安全文本引用，保留原样本继续验账。还在首次读取前校正模型持久字段名为 response。恢复没有新收费调用或第二笔退款，失败不能归为业务退款失败。

Docker PG 上相关 33 项测试全部通过，0 跳过，6.40 秒；脚本 Ruff/格式通过。Java 本轮执行构建，未重跑全部 Java 单测；网页服务健康及买家 HTTP 状态验证通过，没有重做浏览器逐页视觉验收。之前 805 相关项、28 Harness、14 strict 和真实 32 例结果保留，不能把本轮一个业务样本当整体质量提升。独立人审标签仍为 0，官方语义准确率仍 null，公开文档仍未自动采用为商家退款政策。

## 容器隔离与当前代码回放

发现既有 `test_replay_container_isolation` 固定连接 55432，而本机业务库在 55433：原断网失败不能排除“数据库本来未启动”的假阳性。改为解析 fixture 真实 DSN、保留实际端口，并增加同参数联网正对照。联网容器真实向隔离 schema 的 probe 表写入 1 行，确认后删除；仅将 network 改为 none 时，相同写入触发 OperationalError，表中 0 行。不是写入任何业务工单/金额表。

测试先在 cached 镜像通过 1 项/0 跳过（2.72s，[记录](container-isolation-tests.xml)），然后按原 `infra/replay.Dockerfile` 和 uv 冻结锁重建当前代码镜像，又通过 1 项/0 跳过（2.61s，[当前镜像记录](container-isolation-current-tests.xml)）。这是同一项在不同镜像验证，不能相加当两个不同测试。镜像 SDK 为 AgentScope 2.0.8；本机 Python 3.12.13，新容器基础镜像实际 Python 3.12.15，未改变锁或把跨平台结果当完全相同运行环境。

新镜像 `sha256:37499a589bb738d548f6975449b98330522b13e75d39877cdd8c3c7272fec118`，无网络/只读/非 root/无 capabilities/仅临时 tmpfs，未转发模型或业务凭据。strict v13 的 14 包全部 MATCH，[机器记录](docker-strict.json)。里面 model_calls/tool_calls 是既有记录的回放步数，不是实际新增 API；临时写入探针故意传入 fixture 的 PG 凭据以测试拒绝，与标准 strict 无凭据配置区分。未修改旧 pack/manifest 或回源补数据。

```powershell
docker build -f infra/replay.Dockerfile -t resolveflow-replay:local .
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_replay_container_isolation.py -q --junitxml reports/rag-deployment/container-isolation-current-tests.xml
# 每个固定包用相同限制运行；下面命令可替换成任一该 profile 的包。
$pack=(Resolve-Path evals/replay/rag-delivery-v13/short_references).Path
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 --pids-limit 64 --memory 1g --cpus 1 --tmpfs /tmp:rw,nosuid,noexec,size=32m --mount "type=bind,src=$pack,dst=/pack,readonly" resolveflow-replay:local
```

实际逐包循环由 ignored `tmp/rag-docker-strict.py` 调用上述同参数命令，先确认包数 14、保存镜像 ID，再逐包断言 exit 0/MATCH；结果一次写入拒绝覆盖。最终只读确认原业务模型调用仍 18、5 run 均 COMPLETED、generation 共 27；status 九项通过。当前批次新增 3 次真实模型请求，没有为容器检查发送模型请求。
