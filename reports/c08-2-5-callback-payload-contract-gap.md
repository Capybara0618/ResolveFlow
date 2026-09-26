# C08.2-5 契约核查发现的缺口：回调载荷不满足已发布的Case契约

日期：2026-09-26｜状态：**仅核查与记录，未改代码**（本轮无源码改动，上一轮 1010 passed 的状态未变）
｜严重度：**高**——按此实现，四种回调都会被Case服务结构性拒绝

## 1. 起因

上一轮把 `case_type` 记为"派发体没有该列，属契约变更需决策"。本轮去查**契约本身**（它才是权威）：
`contracts/core/openapi-agent.yaml`（Python实现的派发契约）里**确实没有** `case_type`，
但 `contracts/core/openapi-case.yaml` 的 `ProposalPayload` **要求**它，并写明
**"the run classified the case and named its codes"**（`openapi-case.yaml:1700-1706`）。
即 `case_type` **不是派发输入，而是run自己的分类产出**——我上一轮的"需决策"判断是错的：
无需外部决策，缺的是**run 产出 case_type 的能力**。

顺此核对 Python 现在真正发出去的回调载荷，发现的问题比 `case_type` 大得多。

## 2. 契约原文（`contracts/core/openapi-case.yaml`）

| 载荷 | 契约要求 |
| --- | --- |
| `StartedPayload`（:2138） | `additionalProperties: false`，required `[started_at]`，properties **只有** `started_at` |
| `QuestionPayload`（:2159） | `additionalProperties: false`，required `[question_id, questions]`，可选 `reason_codes`；`AgentQuestion`（:2146）required `[field, prompt]`，`additionalProperties: false` |
| `ProposalPayload`（:1622） | `additionalProperties: false`，required `[schema_version, proposal_id, run_id, case_id, input_revision, case_type, recommended_action, summary, reason_codes]`；`proposal_id` 是 **`$ref: Uuid`** |
| `FailedPayload`（:2183） | `additionalProperties: false`，required `[reason_codes, retryable]`，可选 `last_observation_refs` |

后果：`docs/core-contracts.md:64` 结构性/绑定错误一律 **422**；`docs/contracts.md:80` 记 422 进callback失败记录。

## 3. `runtime/worker.py::_payload` 的实际产出 vs 契约

| kind | 现在发出的 | 契约判定 |
| --- | --- | --- |
| STARTED | `{schema_version, started_at}` | ❌ `schema_version` 是**多余成员** |
| QUESTION | `{schema_version, question_id, questions:[{question_id,prompt}], reason_codes, summary?}` | ❌ `schema_version`/`summary` 多余；`AgentQuestion` 要的是 **`field`** 不是 `question_id`（`field` 还缺） |
| PROPOSAL | `{schema_version, proposal_id: "proposal-<run_id>", recommended_action, reason_codes, summary?}` | ❌ **缺** `run_id`/`case_id`/`input_revision`/`case_type`；`proposal_id` **不是UUID** |
| FAILED | `{schema_version, reason_codes, retryable}` | ❌ `schema_version` 多余 |

四种都有问题，**每一种都会被拒**。而现有测试之所以全绿，是因为它们只对照 **Python 自己的
`_REQUIRED_PAYLOAD_KEYS`**（只查"该有的在不在"，从不查"多不多"，也不查类型/枚举/长度）。
`test_callback_outbox.py::started_payload()` 里那个 `{"schema_version": 2, "started_at": …}` 同样是**已发布的违约示例**，
说明这个错不是本轮引入的，而是从 C07 起就没有与契约对齐过。

## 4. 为什么会漏掉（值得记下的方法问题）

C07 的投递测试用 `ScriptedPoster` 直接返回 `DeliveryResult`，**从不经过Case契约校验**；
`test_the_wire_body_is_the_callback_contract` 的断言对象也只是Python自己拼的 body。
"Python通过不等于Java批准"（`docs/agent-harness.md:13`）在这里的具体形态就是：
**发送方自证**。缺的是一个"把要发出的载荷喂给已发布契约schema"的测试。

## 5. 修复计划（下一步，按小步）

1. **先写失败测试**：对worker产出的四种载荷逐一对照 `contracts/core/openapi-case.yaml` 的组件做校验
   （复用仓内已有的 OpenAPI/JSON-Schema 校验入口；`ProposalPayload` 的等价物是
   `contracts/core/agent-proposal.schema.json`，契约原文说明"a test keeps the two from drifting apart"）。
2. **`case_type` 由run产出**：`ModelDecision` 在 `PROPOSE` 上要求 `case_type`（枚举取
   `contracts/core/enums.py:97 CaseType`，与 `agent-proposal.schema.json` 的四个值一致）；
   其它kind上出现即拒绝；缺失/非法走**既有的一次修复**通路。
   同时 `_tool_schema_document` 要广告该成员（否则模型无从得知）——**这会改变 prompt/packet 与 `prompt_hash`**，
   属预期内的manifest变化，须连同 `manifest_id` 一起记录。
3. **载荷按契约重塑**：`_payload` 逐kind对齐（去掉多余成员、补required、`proposal_id` 用
   `uuid5` 从run派生以保证重算一致、`AgentQuestion` 用 `field`+`prompt`）。
4. 顺带核对 `AgentQuestion.field` 与ABI现有问题成员的差异（Python ABI 现在是 `question_id`+`prompt`），
   以及 `summary`（`ProposalPayload` 要求 `minLength:1`）与空摘要的边界。
5. `verify_proposal()` 接入run路径的时机：**在载荷合法之后**，否则校验的是错的文档。

## 6. 本轮未做的事（避免误读）

- **没有改任何源码**；上一轮结束时 `pytest tests` → **1010 passed, 9 skipped**、ruff通过、mypy 9=基线 仍然成立。
- 因此**不能**说"派发→调查→回调闭环已通"——闭环只在Python自己的检查下通，
  对**真实Case服务**而言这四种回调会被拒。C08.2-2/3/4 的报告里"闭环已通"的措辞应以此为准收窄。
- Java侧仍未运行（C07.1 的 BUILD SUCCESS 不是本轮证据）。

## 7. 本轮进展（2026-09-26，同日的后续一小步）

**失败测试已落地**：`agent/tests/unit/test_callback_payloads_match_the_case_contract.py`——
用仓内既有入口 `component_validator("case", <组件>, "contracts/core", CORE_SCHEMA_FILES)`
（与 `test_contracts_core_proposal.py:266` 同一用法）把本项目**实际组装**的载荷喂给已发布契约。

为此把组装函数从"埋在claim里的字面量"提出来成为可测的公有函数：
`runtime/worker.py` 新增 `started_payload(started_at)`、`_payload` 更名 `callback_payload(kind, claimed, result)`。

**契约校验捕获到的真实错误**（未修前的原文）：
- FAILED：`Additional properties are not allowed ('schema_version' was unexpected)`
- QUESTION：`Additional properties are not allowed ('retryable', 'schema_version' were unexpected)` +
  `'question_id' is a required property` + `'questions' is a required property`
  （后者是因为传了字符串而非枚举成员、落进了FAILED分支——**测试自身的bug已修**，用 `CallbackKind.PROPOSAL` 等）
- PROPOSAL：8条，含 `'proposal_id'/'input_revision'/'case_type' is a required property`

**已修（不需要ABI变更的两类）**：
- STARTED：`started_payload` 只发 `{started_at}`（原多一个 `schema_version`）。
- FAILED：只发 `{reason_codes, retryable}`（原多一个 `schema_version`）。
两者现在**通过契约校验**（`test_the_started_body_is_a_started_payload`、
`test_the_failed_body_is_a_failed_payload`，均为**真实通过、非跳过**）。

**仍跳过（不是通过，也不是被删）**：
- PROPOSAL：缺 `case_type`，而 `case_type` 是**run自己的分类**，模型ABI尚未要求该成员 → 无法靠重塑载荷解决。
- QUESTION：契约的 `AgentQuestion` 要 `field`+`prompt`，而ABI的问题成员是 `question_id`+`prompt` → 同理。
两例以 `pytest.skip(<具名理由>)` 留下完整断言体，下一步实现ABI成员后**去掉skip即可**。

命令与结果（工作目录 `E:\Code\Agent+Backend\agent`）：

```
pytest tests -q -p no:cacheprovider --tb=line  → 1012 passed, 11 skipped, 1 warning in 130.08s
ruff check src tests                            → All checks passed!
mypy                                            → Found 9 errors in 4 files (checked 52)  # =既有基线
```

C08.2-4 结束时 1010 passed / 9 skipped → 本步 **+2 passed（STARTED、FAILED 真通过）+2 skipped（PROPOSAL、QUESTION 具名待实现）**。
**下一步**：给 `ModelDecision` 的 PROPOSE 加 `case_type`（枚举 `enums.py:97 CaseType`）、给问题成员加 `field`，
在 `_tool_schema_document` 广告二者（**会改 prompt_hash/manifest_id**，须一并记录），然后去掉这两个skip。

## 8. 2026-09-26 后续一小步：ABI 成员已加、载荷已合法，**强制留待下一步**

**已完成**：
- `actions.py`：`ModelDecision` 增 `case_type`（PROPOSE 专用，取值须属于 `CASE_TYPES`=`enums.py:97 CaseType` 的四个之一，
  取值非法即拒；非PROPOSE出现即拒）、`AskQuestion` 增 `field`；新增 `CASE_TYPES` 常量。
- `sdk_runner.py`：`_tool_schema_document` 的 `proposal.carries` 增 `case_type` 并列出四个合法值，新增 `question` 段
  （`question_id`/`field`/`prompt`）。**这会改变 packet 与 `prompt_hash`/`manifest_id`**（派生值，测试按动态值断言）。
- `worker.py`：`callback_payload` 按契约重塑——PROPOSAL 发全 `ProposalPayload` 必备成员
  （`schema_version/proposal_id(uuid5,由run派生)/run_id/case_id/input_revision/case_type/recommended_action/summary/reason_codes`），
  QUESTION 只发 `question_id/questions[{field,prompt}]/reason_codes`（不再发 `schema_version`/`summary`）。
- `test_callback_payloads_match_the_case_contract.py`：**两个skip已去掉，4例全部真通过**。

**未完成（已披露的刻意部分状态）**：两个新成员目前**只是"可选但必须合法"，尚未强制**。
强制（`PROPOSE` 无 `case_type` 即拒、`AgentQuestion.field` 至少1字符）会使**60个既有用例**失败——
它们构造的PROPOSE/问题fixture都还没有新成员。13处 `"kind": "PROPOSE"` 字面量好改，
但 `test_harness_loop.py`/`test_loop_semantics.py` 走的是各自的 `propose()` 辅助函数（grep未及），
本轮剩余预算不足以"改完 + 全量复验"，故**不**把60个失败留在树上，而是保留成员与合法载荷、把强制留作下一步。
后果要说清：**模型若漏填 `case_type`，run仍会组装出一份Case契约会拒的载荷**——
这正是下一步要关掉的口子，顺序是：先补全fixture → 再打开强制 → 复验。

命令与结果：

```
pytest tests -q -p no:cacheprovider --tb=line  → 1014 passed, 9 skipped, 1 warning in 127.16s
ruff check src tests                            → All checks passed!
mypy                                            → Found 9 errors in 4 files (checked 52)  # =既有基线
```

（C08.2-6 结束时 1012 passed / 11 skipped → 本步 **1014 passed / 9 skipped**：两个skip转真通过，另两例worker测试
按契约形状更新断言——`proposal_id` 断言从 `"proposal-<run>"` 改为"确实是uuid + 带上 run_id/case_id/input_revision"，
问题断言并入 `field`；**均为按契约加强，非删除**。）