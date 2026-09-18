# 跨语言契约 fixture

正确与错误的请求/事件样例，Java 与 Python 必须对同一 fixture 产生相同结果，由 T02 建立。示例文件头部的 `_comment` 说明了每份语料的用途，本文件说明它们如何被使用与再生成。

## 内容

| 文件 | 作用 |
| --- | --- |
| `examples/cross-language-canonical-inputs.json` | 规范化（RFC 8785）与 `payload_hash` 的输入：执行载荷、任意文档、`_` 注解、`invalid_payloads`（必须拒答的哈希输入） |
| `examples/valid.json` | 正向语料：执行命令、事件载荷、消息信封、Agent 方案、Harness manifest、错误体、OpenAPI 外部/内部样例，逐条声明应满足的 schema |
| `reject/reject.json` | 反向语料：每个条目都是「必须被拒绝」的实例，并写明拒绝理由；由对应的 schema 断言其确实被拒 |
| `expected-hashes.json` | 冻结值：`execution_payload_hashes`、`content_hashes`、`canonical_documents`、`signing_inputs`、`event_signatures`、`signing_keys`、`placeholder_values` |
| `expected-enums.json` | 冻结值：23 组跨语言枚举的线上取值 |

## 生成与校验

冻结值由 Python 生成，Java 只独立重算、不生成（`docs/contracts.md:17` 要求两侧对同一 fixture 得到相同字节）：

```
uv run --project agent python scripts/contracts_freeze.py            # 重新生成冻结值
uv run --project agent python scripts/contracts_freeze.py --check    # 只校验：语料仍与冻结值一致
pwsh -File scripts/verify.ps1 -Suite contracts                      # 冻结校验 + Python 契约测试 + Java 契约测试
```

`--check` 不写文件；语料或实现改动后若与冻结值不一致，它必须失败。**不要为了让测试通过而重新冻结**：先判断是语料有意变更，还是规范化实现回退。

签名密钥是 T02 的测试密钥，明文保存在 `expected-hashes.json`，仅用于让两侧验证同一签名输入与签名算法；它不是任何环境的生产密钥。

## 占位符

语料用 `PLACEHOLDER_*` 标记相互引用的值（如某个载荷的 hash、某个信封的签名）。生成器解析引用、代入真实值、再校验整份语料，因此语料内部不会出现复制粘贴导致的不一致。`placeholder_values` 记录代入后的值，`require_placeholder_coverage` 保证没有「引用了但没冻结」或「冻结了但没人引用」的占位符。

## 两侧的对等测试

- Python：`agent/tests/unit/test_contracts_canonical.py`、`test_contracts_fixtures.py`、`test_contracts_openapi.py`
- Java：`java/shared-kernel/src/test/java/com/resolveflow/shared/contract/`

两侧都读同一批文件：只改一侧会让另一侧失败，而不是让某一侧静默漂移。
