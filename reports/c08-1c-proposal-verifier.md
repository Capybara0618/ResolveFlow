# C08.1c-1 候选引用验证（ProposalVerifier）

日期：2026-09-26｜状态：**已完成（Python侧）**｜未开始：C08.1c-2（模型输出可修复一次）、C08.2 worker

## 1. 起点：一个必须先修的缺口

C08.1b-2 结束时发现的真实缺口：`ModelDecision` 是 `extra="forbid"` 且**没有**任何引用成员（只有
`reasoning/reason_codes/kind/tool_name/arguments/cursor/query/observation_id/questions/recommended_action/summary`）。
即：模型**根本无法**提交引用，而冻结Schema `urn:resolveflow:core:agent-proposal:v2` 要求 `REFUND` 必须至少各一条
`evidence_refs`/`policy_refs`。若只写校验器，它永远不可达——校验一个模型不可能填的字段。
所以本步同时做两件事：**先让ABI能表达引用**，再**校验引用**。

第二处缺口：P0 里的 `HARNESS_SYSTEM_PROMPT` 只说 "PROPOSE it and cite what you saw"，`_tool_schema_document`
只列 `actions`/`tools`，从未出现成员名。校验器拒绝一个模型猜不到的成员名，是harness的错，不是模型的错。

## 2. 改动（先失败测试，再实现）

失败测试先行：新增 `agent/tests/unit/test_proposal_verifier.py`（15例），首跑为
`ModuleNotFoundError: No module named 'resolveflow.harness.verifier'`，确认RED后再实现。

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/harness/verifier.py` | **新增**：`ProposalVerifier`、`CitationRefusal`、`VerificationResult`、6个稳定reason code |
| `agent/src/resolveflow/harness/actions.py` | `ModelDecision` 增 `evidence_refs`/`policy_refs`/`missing_evidence`（复用契约类型 `CoreEvidenceRef`/`CorePolicyRef`，不另抄一份更宽的本地形状）；validator 增"只有 PROPOSE 可带引用" |
| `agent/src/resolveflow/harness/sdk_runner.py` | `ActionGateMiddleware.verifier` + `_verify_proposal()`；`_GateAwareClient.__init__` 用**它自己那个** observations 列表构造校验器并挂到gate；`_tool_schema_document` 增 `proposal.citations` |
| `agent/src/resolveflow/harness/manifest.py` | `VERIFIER_VERSION`：`unimplemented` → `python-citations-v1`（故 `manifest_id` 变化，这是正确行为） |
| `agent/tests/integration/test_context_wiring.py` | +2例（拒绝路径端到端、引用成员出现在实际请求里）；共享 `propose()` 改为 `MANUAL_REVIEW` + 新增 `propose_refund()` |
| `agent/tests/unit/test_harness_loop.py`（等5个测试文件） | 把"顺带用 REFUND 结尾"的脚本改为 `MANUAL_REVIEW`（见§5） |

### 校验规则（`docs/agent-harness.md:13` 的四项）

1. **Schema**：`verify_proposal()` 用**冻结**的 `urn:resolveflow:core:agent-proposal:v2`（`validator_bundle(..., CORE_SCHEMA_FILES)`），
   不用更宽松的Python本地形状——否则"这里过、Java拒"的正是本检查要防的分歧。
2. **可见引用**：`evidence_refs` 必须匹配本次run真实产生过的 observation（按 `observation_id`），**且逐成员**
   （`source_ref`/`source_version`/`content_hash`）一致。只查id会放过"真id配伪造字节"。
   失败读没有 `source_version`/`content_hash`（契约类型自己就强制"一起有或一起无"），故不可引用。
3. **hash/版本**：任一成员不等 → `CITATION_HASH_MISMATCH`（含"引用了run没见过的版本/hash"）。
4. **缺证检查**：`REFUND` 无引用 → `REFUND_CITATION_REQUIRED`；`REFUND` 同时报 `missing_evidence` →
   `MISSING_EVIDENCE_ON_REFUND`。
5. **跨scope/政策固定版本**：`policy_refs.bundle_id` 不在派发pin的 `bundle_ids` 内 → `CROSS_SCOPE_CITATION`
   （该引用本身格式完好、也能通过可见性检查，所以必须是**独立**的拒绝码，不能并进"不可见"）。

政策命中**从 `SEARCH_POLICY` observation 自己的 `result["hits"]` 读取**，不另立引用台账：这样"模型看到什么"与
"什么可被引用"不可能漂移，也满足 `docs/policy-rag.md:25`（Python检查是实际返回过的引用）。

### "Python通过不等于Java批准"

`VerificationResult.note` 常量 `NOT_APPROVAL` 携带该边界（`docs/agent-harness.md:13`、
`docs/core-contracts.md:74`：Java 自己按固定 `source_ref` 映射重读）。有一个测试断言它，而不是只写在注释里：
只读 `ok` 的调用方不会把通过误当授权。

## 3. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 970 passed, 9 skipped, 1 warning in 122.49s
.\.venv\Scripts\python.exe -m ruff check src tests
  → All checks passed!
.\.venv\Scripts\python.exe -m mypy
  → Found 9 errors in 4 files (checked 50 source files)   # =既有基线，非全绿
```

基线对比：C08.1b-2 结束时 953 passed / 9 skipped → 本步 **+17例**（15例校验器单测 + 2例集成）。
mypy 9 项为固定基线（`no-any-return`：provider_stub 3、`_schemaio` 1、`fixtures` 1、`core_corpus` 4），未新增、未修。

未运行：Java 全量套件（上次 BUILD SUCCESS 在 C07.1）；`spikes/agentscope` 套件；`all-offline` 门禁重跑。

## 4. 过程中修正的两个自身错误

- mypy 飘到 10：新局部变量名 `refusal` 与 `check()` 里已有的 `except ... as refusal` 同名
  （`Assignment to variable "refusal" outside except: block`）→ 改名 `citation_refusal`，回到9。
- 我自己写的一个测试断言错了：用 `source_version=""`/`content_hash=""` 构造失败observation，被契约类型拒绝
  （`string_too_short` / `string_pattern_mismatch`）。是**测试**错、不是实现错：失败读必须**省略**这两个字段。
- 施工中还误删了 `note_stop` docstring 首行（`edit` 的 old_string 选短了），同回合修复并复跑导入检查。

## 5. 为什么5个既有测试文件的脚本被改（不是删断言）

改完后这些测试红了，且**红得正确**：它们都以"裸 REFUND 提议"结尾，而REFUND现在必须引用。它们是关于
packet/预算/loop/搜索可见性的，不是关于引用的：

- `tests/unit/test_harness_loop.py`、`tests/unit/test_loop_semantics.py`（2个参数化用例）、
  `tests/integration/test_harness_mcp.py`（3处）、`tests/integration/test_observation_read_loop.py`、
  `tests/integration/test_context_wiring.py`（共享 `propose()`）→ 终局提议改为 `MANUAL_REVIEW`。

每处都保留了原有断言的**全部**语义（调用次数、observation数、packet内容、cursor、错误回传、trace），只改了
"提议的是什么动作"，并就地注明原因。REFUND_CITATION_REQUIRED 的端到端拒绝路径与引用成员入请求，另有2例新测试。
**没有删除任何断言来变绿。**

## 6. 未完成（下一步）

- **C08.1c-2：模型输出 Schema/引用"可修复一次"**（`docs/agent-spec.md:52`）。当前是不可修复的硬停止：
  引用不可校验即 `completed=False`，且 `result.decision is None`。规格给模型一次修复机会——这属循环级改动
  （喂回拒绝原因 + 多一次模型调用，且必须计预算），未实现。**这是本步与规格的已知差距，不宣称已满足**
  `agent-spec.md:52`。
- **端到端"通过型退款"用例**：需要一个"真实工具observation + 真实政策命中"的双来源fixture。
  现有fixture二缺一：`test_context_wiring` 有工具无政策索引，`test_policy_search_action` 有索引但 `_NoTools()`。
  目前"通过"只在单测层证明（observation + 命中 → REFUND 通过），命中成员与引用成员一致由
  `test_policy_search_action.py:135` 断言。
- `verify_proposal()`（整份v2 Schema校验）**已实现但尚未接入run路径**：run只知道 `ModelDecision`，
  `proposal_id`/`case_type` 等由运行时在组装callback时补（`docs/agent-harness.md:31`），属C08.2 worker。
- `PolicySearchBridge` 的 `source_ref` 是 `policy:<bundle>/<chunk>`，与命中项里的 `source_ref` 字段不同名同值；
  证据引用侧不存在这个问题，若将来政策引用也要求 `source_ref` 需再对齐。

## 7. 下一步

C08.1c-2（修复一次）→ C08.2 单执行者业务闭环（PG待办run领取 + 问题/方案/失败 `callback_outbox` +
补证新run/旧结果STALE + mock/live配置工厂）。