# 核心版 fixture（v1.2）

核心协议的正向语料。与 `contracts/fixtures/`（T02 compat 基线）并列存在，不替换它：旧语料保持原样，因为 `docs/core-scope.md:34` 明确保留旧协议、旧测试与旧 fixture 作为兼容资产。

| 文件 | 作用 |
| --- | --- |
| `valid.json` | 正向语料：执行命令、四种事件信封、提案（可执行与追问各一条），以及被它们引用的共享组件与测试签名密钥 |
| `reject.json` | 反向语料：每条都是「必须被拒绝」的实例，并写明为什么必须被拒 |

## 语料结构

顶层只有下面这些节，多一个少一个都会被 `agent/tests/unit/test_contracts_core_corpus.py` 断言出来：

| 节 | 校验用的 schema |
| --- | --- |
| `execution_commands` | `urn:resolveflow:core:refund-command:v2` |
| `message_envelopes` | `urn:resolveflow:core:event-envelope:v2` |
| `agent_proposals` | `urn:resolveflow:core:agent-proposal:v2` |
| `components` | 支撑块：被别的条目引用的完整对象 |
| `signing_keys` | 支撑块：测试签名密钥 |

**节与 schema 的对应写在代码里**（`agent/src/resolveflow/contracts/core_corpus.py` 的 `CORE_SCHEMA_SECTIONS`），不写在语料里。理由与 compat 语料相同：语料不能自己挑校验器，否则一份 fixture 可以给自己选一个更宽松的 schema，然后「通过」。

## 引用与占位符

- `payload_ref`：信封用它指向 `components` 里的载荷，这是 compat 语料既有的约定。
- `_ref`：顶层别名（例如 `"lost_parcel_full_line": {"_ref": "components.refundCommandLostParcel"}`）。核心语料显式支持它，因为 compat 的解析器会把所有 `_` 开头的键当作注解丢掉，顶层别名会被解析成空对象——一份「通过校验的空 fixture」比没有 fixture 更糟。**`_ref` 是唯一一个含义为「替换我」而不是「读我」的下划线键。**
- `_comment` 等注解会被**递归**清理，包括被引用组件内部的注解；否则注解会随引用进入实例，而这里每个 schema 都是 `additionalProperties: false`。

以 `PLACEHOLDER_` 开头的值由 `core_corpus` 在解析时按权威规则**重算**，而不是冻结在某个文件里：

| 占位符 | 重算规则 |
| --- | --- |
| `PLACEHOLDER_CORE_PAYLOAD_HASH_*` | SHA-256 over canonical JSON，只覆盖 `docs/core-contracts.md:17` 与 `:18` 列出的 12 个字段（不含 `payload_hash` 自身） |
| `PLACEHOLDER_CORE_SIGNATURE_*` | Ed25519 over 规范化信封，覆盖除 `signature` 自身以外的全部成员（含 `signing_key_id`，`docs/core-contracts.md:19`） |

不冻结是为了避免「语料里抄了一份摘要、看起来自洽、却与哈希实现不一致」——那正是冻结值最容易失效的方式。Ed25519 签名是确定性的，`payload_hash` 是纯函数，所以每次重算都得到同一结果；测试断言两次重算相等，并断言**没有**占位符被留下、也没有占位符被填了却没人用。

## 签名密钥

`signing_keys.core-fixture-key-1` 是 **RFC 8032 第 7.1 节 TEST 1 的公开测试向量**，明文保存是刻意的：Java 与 Python 必须用同一密钥签出同一字节，才算证明了签名算法一致。它不是任何环境的生产密钥，也不是需要保护的秘密。`core_corpus` 会校验种子推导出的公钥等于语料声明的公钥，抄错会当场失败。

## 为什么核心不能复用 compat 的签名函数

`resolveflow.contracts.events.signing_input_bytes`（compat）与 `core_signing_input_bytes`（核心）签的是**不同字节**：核心信封去掉了 `aggregate_id`/`aggregate_version`，新增了 `topic`。复用 compat 规则会给核心信封补上两个它并不声明的 `null` 成员、并漏签 `topic`，于是两侧各自自洽却互相验不过。测试因此直接断言两者的签名输入不相等，并断言核心的签名键集合恰好等于核心 Schema 声明的成员减去 `signature`。

## 反向语料

`reject.json` 的每一节声明「这一节的实例必须被哪个 schema 拒绝」，由 `CORE_REJECT_TARGETS` 固定（同样写在代码里）。四条要求：

1. **每条都要写明为什么必须被拒**（`why`），且理由里要引用权威行号——没有引用的理由只是个人意见。
2. **拒绝必须真的发生**：如果某条负例开始被接受，说明协议回退了，要修的是 schema 而不是负例。
3. **增量既必要又充分**：绝大多数条目用 `base` 指向正向语料里的对象，再给 `overrides` / `remove` 表达「差在哪」。测试会同时断言「改过的必须被拒」与「没改的必须仍被接受」——否则一条「本来就无效」的负例可以永远通过，却什么都没测。
4. **`remove` 删一个不存在的路径要当场失败**，否则「本该缺少某字段」可能其实什么都没删。

`canonical_payloads` 一节不由 schema 拒绝，而由哈希实现拒绝：整数金额、`2^53-1` 上界、摘要覆盖哪些字段（以及补发走的是另一套字段），都无法用「约束摘要输入」的 JSON Schema 表达，所以按生产者调用哈希的方式断言它报错——**悄悄算出一个摘要比算错更糟**，两侧会对一个不该存在的东西达成一致。

覆盖情况：命令 15 条、信封 13 条、提案 19 条、摘要输入 4 条，共 51 条；每个核心 schema 都有负例（`test_every_core_schema_has_negative_coverage`）。

## 校验命令

```
uv run --project agent --frozen pytest agent/tests/unit/test_contracts_core_corpus.py agent/tests/unit/test_contracts_core_reject.py -q
pwsh -File scripts/verify.ps1 -Suite contracts
```