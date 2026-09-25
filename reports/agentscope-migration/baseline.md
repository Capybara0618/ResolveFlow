# AS00 接管与基线

2026-09-25。`tasks/todo.md` 的 AS00 要求：核实 HEAD/工作区/旧 DSH 是否仍写，接管 C06.4⑤ 并记录**当前可复现基线**；区分用户改动与迁移新改动；真实 Java 联调证据与 HTTP 桩证据分开；明确 scope 守卫/worker/mypy 欠账。**不据文件存在判通过。**

## 1. 现场（动手前，真实执行）

| 项 | 值 |
| --- | --- |
| HEAD | `b2b5444`（`main`，= `origin/main`，已推送，未推送提交 0） |
| 工作区 | 31 项改动：**7 项 C06.4⑤ 代码/测试/脚本** + **24 项 v1.3 文档重写**（含新增 `docs/agentscope-migration.md`） |
| 容器 | 未在 AS00 重新校验；C06.4 期间 postgres(55432)/mysql(3306) healthy |

### 1.1 旧 DSH 是否仍写：**否**（已核实）

代码文件最后写入时间为 `09-25 12:34–12:37`，全部早于本轮接管；`git diff --stat` 显示 7 项代码改动的规模与 C06.4⑤ 移交时一致（`catalog.py` +34、`stub_upstream.py` +38、`test_tool_credential.py` +36、`test_tool_catalog.py` +75、`ApiExceptionHandler.java` +15，另 2 个新 Java 文件与 1 个新脚本）。v1.3 文档重写是用户侧完成的，**未与代码改动交叉**。因此无并行写冲突，可以接管。

### 1.2 C06.4⑤ 改动与其归属

| 文件 | 性质 | 谁改的 |
| --- | --- | --- |
| `java/.../internal/CaseEvidenceInternalController.java`（新，89 行） | C06.4⑤ 新路由 | 迁移前会话 |
| `java/.../casefile/CaseEvidenceInternalApiTest.java`（新，205 行） | 其 5 例测试 | 迁移前会话 |
| `scripts/e2e_harness_java_tools.py`（新） | 真实 Java 工具联调驱动 | 迁移前会话 |
| `agent/src/resolveflow/tools/catalog.py` | policy-manifest 形状修正 | 迁移前会话 |
| `agent/tests/{integration/stub_upstream,integration/test_tool_credential,unit/test_tool_catalog}.py` | 形状守卫与 run id 派生 | 迁移前会话 |
| `java/.../error/ApiExceptionHandler.java` | 新路由 404 映射 | 迁移前会话 |
| `docs/agentscope-migration.md` + 23 份文档 | **v1.3 文档重写**（本轮迁移规格） | 用户 |
| `tasks/todo.md`、`tasks/plan.md`、`README.md`、`AGENTS.md` | 同上 | 用户 |

**接管动作（本会话，属迁移新改动）**：C06.4⑤ 遗留的一个失败测试修好并加固（见 §3），`scripts/e2e_harness_java_tools.py` 的 run id 派生改为调用生产函数。**没有覆盖用户改动。**

## 2. 接管前基线（真实命令）

```powershell
git log -1 --oneline                      # b2b5444
git rev-parse HEAD origin/main            # 两者相同
git rev-list --count origin/main..HEAD    # 0
git status --porcelain                    # 31 项
```

```powershell
# 迁移规格 §7 的聚焦测试
uv run --project agent --frozen pytest agent/tests/unit/test_harness_loop.py agent/tests/integration/test_harness_mcp.py -q --basetemp=.../tmp/pytest-basetemp-as00
# -> 41 passed

# Python 全量
uv run --project agent --frozen pytest agent/tests -q --basetemp=.../tmp/pytest-basetemp-as00
# -> 748 passed, 9 skipped, 1 failed
```

那 1 个失败是 **`test_tool_credential.py::test_the_credential_matches_the_run_id_case_derives`**，是迁移前会话中断时留下的：它把一个测试内定义、又用自己比自己的辅助函数当断言（恒真），且 `scripts/e2e_harness_java_tools.py` 里的同源派生用了 `uuid.NAMESPACE_DNS`——**那是错的命名空间**，会算出 Case 从未派生过的合法 v5 id，症状是"凭据路由说这个 run 不存在"。已按下节修好。

**接管后复跑（本次记录的实际基线）**：

```powershell
uv run --project agent --frozen pytest agent/tests -q --basetemp=.../tmp/pytest-basetemp-as00
# -> 750 passed, 9 skipped, 0 failed
```

`--basetemp` 指向 `tmp/pytest-basetemp-as00`：本机 `%TEMP%\pytest-of-<user>` 不可写（WinError 5），且 `tmp/` 已在 `.gitignore` 内，不会把含用户文件的目录交给会清理目录的参数。

## 3. 本会话对 C06.4⑤ 的收口（迁移新改动）

1. **run id 派生移入生产代码**：新增 `resolveflow/runtime/runs.py::agent_run_id_for` + `RUN_NAMESPACE`（RFC 9562 v5，SHA-1 取**前 16 字节**、置版本/变体位）。过程中真实失败一次：把 20 字节 SHA-1 全量传给 `uuid.UUID(bytes=...)` → `ValueError: bytes is not a 16-char string`（测试抓到的，不是猜的）。
2. **原测试换成真正的跨语言钉**：改为从 `AgentRunId.java` **解析出命名空间字面量**、在测试内独立重算、要求生产函数一致。原来那个自比自的断言删掉了。**故意弄红验证过**：把 Python 命名空间改成 `NAMESPACE_DNS` → 该测试红（`Python and Java derive run ids under different namespaces...`），`git hash` 还原后逐字节一致。
3. **e2e 驱动改为调用生产派生**，不再自带 `uuid5`。
4. 现状：`test_tool_credential.py` **10 passed**。

## 4. 证据分级（`docs/agentscope-migration.md:19,21` 要求）

| 证据 | 等级 | 说明 |
| --- | --- | --- |
| C06.4①②③ Harness 循环/预算/MCP 客户端 | **HTTP 桩** | 真 MCP 子进程 + 真握手，但上游是 `stub_upstream`。工具边界是真的，**Java 是桩** |
| C06.4④ Java 工具凭据路由 | **真 Java**（Testcontainers/真 MySQL） | `ToolCredentialApiTest` 10 例 |
| C06.4⑤ Java 内部证据路由 | **真 Java**（Testcontainers/真 MySQL） | `CaseEvidenceInternalApiTest` 5 例 |
| C06.4⑤ 端到端脚本 `scripts/e2e_harness_java_tools.py` | **未运行** | 见 §5 |
| AS01.1 AgentScope 兼容 | **独立 spike + HTTP 桩** | 见 `reports/agentscope-migration/compatibility.md` |

## 5. 未运行 / 欠账（不得读成完成）

- **C06.4⑤ 端到端脚本从未跑过**：它需要起真 case/commerce 与 MySQL。它的存在**不是**"真实 Java 工具联调已完成"的证据；本轮未运行它。
- **scope 守卫缺口仍在**：`docs/core-contracts.md:74` 要求工具凭据绑定 scope，Java 的 `ServiceTokenFilter` 只校验 aud/签名，**不校验 scope**；没有逐路由 scope 强制。不能借框架迁移把这笔欠账写成已完成。
- **run 侧 worker 不存在**：`HarnessRunner` 是可调用类，没有消费 PG 队列的 worker（归 C09）。
- **strict mypy 欠账**：`cd agent; uv run --project . --frozen mypy` → 9 个既有错误（`core_corpus.py`×4、`provider_stub/__init__.py`×3、`contracts/_schemaio.py`×1、`contracts/fixtures.py`×1）。本会话新增代码零错误。
- **Java 4 个 skipped** 是没跑，不是绿的。
- C06.4⑤ 的改动**仍未提交**（本轮未提交，遵从"不擅自推送"）。

## 6. 下一步

AS01.1 已完成（`reports/agentscope-migration/compatibility.md`）。其后 AS01.2 真实 PG 恢复探针 → AS01.3 禁网络回放探针 → 技术门禁审阅。
