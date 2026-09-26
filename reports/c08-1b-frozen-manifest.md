# C08.1b-1 冻结 HarnessManifest（2026-09-26）

范围：`handoff-current.md` §2 C08.1b 第一条——"落实冻结的HarnessManifest，不能将政策bundle@短hash冒充完整运行manifest；
复用现有Schema/类型/fixture，变更协议须同步消费者"。承接同日 [C08.1a](c08-1a-context-path.md)。**C08.1b 其余部分未做**。

## 1. 缺陷（先量）

`ContextPacket.manifest_id` 一直由 `sdk_runner._manifest_id(facts)` 填：

```
f"{bundles[0] if bundles else 'unpinned'}@{manifest_hash[:16]}"
```

这是**政策引用**（`docs/policy-rag.md:25` 的引用形式），不是 manifest，也不是 sha-256：
它没有 pin harness/code revision/AgentScope 版本/prompt/tool schema/context policy/verifier/model/budgets 中的任何一项，
digest 还被截成 16 位。`docs/agent-harness.md:33` 要求的是完整冻结 manifest，且
`manifest_id` = **排除自身后的 canonical SHA-256**。

生产消费者清点：`agent_run`（`runtime/migrations/001_agent_run.sql`）只有 `policy_manifest jsonb`，
**没有** manifest_id 列；`runtime/runs.py:259` 写的是 `policy_manifest.manifest_hash`。全仓库 `manifest_id` 的生产者
只有 `sdk_runner`。所以这是**生产者局部改动**，不涉及协议/消费者同步。

## 2. 实现

新增 `agent/src/resolveflow/harness/manifest.py`，按**已冻结的** `contracts/harness-manifest.schema.json`
（`additionalProperties:false`、全字段必填）构造，`build_manifest()` 返回普通 mapping，因为那正是 schema 校验的对象、
也是快照要存的东西。

| 字段 | 取值来源（真值，非 schema 默认） |
| --- | --- |
| `manifest_id` | `canonical_manifest_id()` = 排除自身后的 canonical JSON 的 SHA-256 |
| `graph_version` | `agentscope@{装到的版本}+resolveflow@{装到的版本}`，由 `importlib.metadata` 读取 |
| `harness_version` | `resolveflow-harness-{版本}` |
| `code_revision` | `RESOLVEFLOW_CODE_REVISION` 环境戳，无则 `"unknown"`（不假装已盖章） |
| `prompt_hash` / `tool_schema_hash` | 实际 system prompt 与**实际发出的** tool schema 文档的 SHA-256 |
| `context_policy_version` | `p0-p4-v1`（`context.py` 的 P0–P4 分层） |
| `token_counter_version` | `utf8-bytes-v1`——`estimate_tokens` 实际用的 UTF-8 字节额度，不是已废弃的 chars/3，也不是 fixture 里过时的 `chars-div-4` |
| `verifier_version` | `"unimplemented"`（见 §3） |
| `policy_manifest_hash` | 派发 pin 的 `manifest_hash`（Java 自己的值） |
| `index_generation` | 见 §3 |
| `model` | 由**实际决策的 client** 自述；`parameters` 只记 client 声明过的键 |
| `budgets` | 该 run 的 `RunBudget` + 规格的 120s active deadline 上限 |

runner 侧：`AgentScopeRunner.manifest()` 首次调用构造并**记忆化**（`frozen_manifest` 字段），`_build_packet` 改用
`self._runner.manifest()["manifest_id"]`。记忆化不是优化而是语义：`docs/agent-harness.md:35` 禁止恢复时静默换 manifest，
逐步重算的 manifest 可能在无人察觉时与快照里那条不同。

## 3. 两个诚实性决定（都已写进代码注释，不是默认值）

1. **`index_generation` 在 Python 侧解析，不改派发协议。** 派发 pin 的是政策**集合**
   （`bundle_ids` + `manifest_hash`，`runtime/runs.py:202-228` 强制要求），真正服务的行有自己的 `generation_id`。
   有 policy index 且该 bundle 在 pin 的 hash 上有 READY generation 时，记**真实行 id**（`PolicyIndex.generation_for`，仅 READY）；
   否则回退为 pin 自身的确定性 uuid5，并在 docstring 里写明**它不是 `policy_index_generation` 行 id、不可按行 id 查**。
   选择解析而非给派发加字段，是因为加字段要同步 Java/OpenAPI 消费者，而现有 schema 与 wire 协议不需要动。
   回退分支只手搓 run 可达（派发必带 pin）。
2. **`verifier_version = "unimplemented"`。** 方案校验器属 C08.1c，尚未存在。写成 `verifier-1` 会宣称一个不存在的校验器；
   C08.1c 落地后该值变化、`manifest_id` 随之变化，这正是需要的语义：**没有校验器的 run 与有校验器的 run 不是同一配置**。

另：`model.provider` 对未自述的 live client 记 `"unknown"` 并附其 `model_alias`，不替它猜一个厂商
（`docs/agent-harness.md:35` 要求 alias 漂移记为限制而非抹平）。

## 4. 测试（先失败后实现）

新增 `agent/tests/unit/test_harness_manifest.py`（8 例）——先在缺模块时红：

1. **满足冻结 schema**：用 `contracts/_schemaio.validator_bundle("urn:resolveflow:harness-manifest:v1")` 校验，零错误。
2. `manifest_id == canonical_manifest_id(manifest)`、64 位十六进制；budgets 变化必须换 id。
3. **id 排除自身**：把 `manifest_id` 改成任意值，重算结果不变。
4. `graph_version` 为 `agentscope@2.0.8+…`、不含 langgraph、不等于 `graph-1`；token counter 不是 `chars-div-4`。
5. pin 的 `manifest_hash` 与 `index_generation` 如实记录。
6. budgets 来自 run 的 `RunBudget` 而非 schema 默认（改 `model_calls=7/tool_attempts=9/local_reads=3` 必须体现）。
7. prompt/tool-schema hash 覆盖实际内容，且换 schema 必须换 manifest id。
8. mock 记 `provider="mock"`；live client 自述优先；未自述的 live 记 `unknown` + alias。

`test_context_wiring.py` 新增 1 例集成断言：报文里的 `manifest_id` **等于**该 run 冻结 manifest 的 canonical hash、
是 64 位、**不等于**旧的 `bundle@hash[:16]` 字符串、budgets 与该 run 一致，且**第二步与第一步相同**（冻结而非重算）。

## 5. 实测（工作目录 `agent/`）

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` | **939 passed, 9 skipped, 1 warning**（C08.1a 后 930 → +9 例） |
| `.\.venv\Scripts\python.exe -m ruff check src tests` | All checks passed（先出现 UP035/S105/E501 三条并修掉；S105 是 ruff 把常量名里的 `TOKEN` 当凭据，已就地 `noqa` 说明） |
| `.\.venv\Scripts\python.exe -m mypy` | **9 errors / 4 files = 基线**（检查 48 个源文件，新增 manifest.py 后仍零新增） |

改动文件：新增 `agent/src/resolveflow/harness/manifest.py`、`agent/tests/unit/test_harness_manifest.py`；
修改 `agent/src/resolveflow/harness/sdk_runner.py`（导入、`manifest()`/`index_generation()`、删 `_manifest_id`、`_build_packet`）、
`agent/tests/integration/test_context_wiring.py`。

## 6. 未做 / 未运行

- **C08.1b 其余**：live `ModelClient`（供应商/参数、强制 `max_output_tokens`、无隐藏重试、usage 未标 ESTIMATED/UNKNOWN、
  脱敏 HTTP 请求与 hash 留存）、候选引用验证、H1 真实模型配对证据，全部未开始。
- **未跑**：Java 全量、`all-offline`、spikes 测试、live 模型。
- **不得宣称**：manifest 已进快照/恢复（C09 才持久化它）、真实模型自主性、C09/C10。
- 遗留：手搓 run 的 `index_generation` 是 pin 的派生名而非索引行 id；C08.2 的 worker 应在 `require_ready` 后用真实生成 id 构建 runner。

## 7. 下一步

C08.1b-2：live `ModelClient` 适配 + 离线请求捕获测试（无 API 预算即可做），随后候选引用验证；
付费 live 小样本与 H1 配对证据需用户确认后再说。