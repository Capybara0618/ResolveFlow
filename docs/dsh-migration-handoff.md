# DeepSeek Harness交接 · v1.3 AgentScope迁移

更新时间：2026-09-25。本文件保存DSH开工索引和跨客户端边界；项目事实、实现状态和验证证据仍以任务账本与代码为准。旧Claude Code迁移档案保留，不作为当前实施计划。

## v1.3优先交接

用户已确认个人项目范围保持不变，仅将LangGraph替换为AgentScope 2.x Python SDK。当前从AS00接管→AS01隔离验证→审阅→AS02生产切换，再回C07–C13；C00–C05已有完成记录，不重做。完整规格和可复制提示词见[agentscope-migration.md](agentscope-migration.md)。代码与依赖锁尚未迁移，不把目标当成果。

先保存当前进度并检查其他客户端是否同时编辑；本轮文档修改前已有8项未提交代码/测试/脚本改动，按实时git状态接管，不能覆盖或丢弃。可收口已有C06.4⑤联调，但停止继续扩展旧循环/LangGraph方案。`docs/c064-handoff.md`仅供迁移前基线与欠账核对。

下方“迁移时的工作断点”只描述此前客户端迁移瞬间，不能覆盖新任务账本。旧contract文档仍供T02兼容测试解析，核心协议要独立迁移，不能直接删除接口/断言来瘦身。

## 继续工作时的读取顺序

1. 根目录 `AGENTS.md`：长期实施约束与不可变规则。
2. `README.md`、`docs/core-scope.md`、`docs/agentscope-migration.md`：范围、替换边界与技术门禁。
3. `tasks/todo.md`顶部/AS区块、`docs/implementation-handoff.md`顶部与`tasks/plan.md`：当前进度、下一任务和依赖；原C06历史按需检索。
4. 当前任务涉及的专题规格、契约、源码和测试；不要用旧聊天覆盖工作区现状。
5. 只有在上述资料无法解释某项历史决定时，才查阅下方 Claude Code 原始档案。

## 迁移时的工作断点（历史快照，非当前进度）

- T00 已完成：依赖兼容与版本锁，记录见 `tasks/todo.md` 与 `reports/t00-compatibility/`。
- T01 已完成：工程骨架、命令入口、基础 CI 与离线验证，记录见 `tasks/todo.md`。
- 最近一次验证使用 PowerShell 7.6.6：`doctor` 通过，`format` 4/4 通过，`unit` 3/3 通过（27 个测试）；相应报告位于 `reports/verify/`。
- 下一项是 T02“契约固化与跨语言 fixture”。开始前先检查工作区和 `tasks/todo.md`，不要仅凭本文件实施。
- Docker 由用户手动启动；这不代表依赖 Docker 的套件已经运行或通过。

## 最近一次 Claude Code 交接结论

- `docs/engineering.md` 已标明尚未实现的命令及其归属任务，避免把未实现入口误报为成功。
- `provider-stub` 属于 T12；不要为了让命令暂时通过而加入不实现支付或物流协议的空占位服务。
- `--profile app`、回放脚本以及尚未实现的验证 suite 必须在各自任务完成后才视为可执行能力。
- T02 若引入新的 OpenAPI 生成依赖，应先实测其与既定 Spring Boot/Jackson 版本的兼容性，再锁定版本。

## 原始会话档案

- Claude Code 原位置：`C:\Users\hjn\.claude\projects\e--Code-Agent-Backend`
- DSH 只读迁移副本：`C:\Users\hjn\.dsh\imports\claude-code\e--Code-Agent-Backend`
- 主会话：`bde7c02c-516d-4e75-88e9-a1d827f432fc.jsonl`
- 迁移时共有 32 个文件、7,618,969 字节。
- 主会话 SHA-256：`3c5deaedc3352538edca51263c28bc08080e796c903600a2f654a1dea721db11`

原始 JSONL、工具结果和 workflow 文件仅用于审计与追溯，不是 DSH 原生 Session 格式，不得复制进 `~/.dsh/sessions` 或当作当前项目状态整体注入模型。需要追溯时先定位具体问题，再按时间或关键词读取最小相关片段。

## 迁移边界

- API Key、凭据、`.env` 和本机私有配置不进入仓库，也不写入本交接文件。
- 旧聊天中的计划、推测和未执行命令不构成完成证据；以代码、测试报告和 `tasks/todo.md` 为准。
- DSH 会原生加载项目根目录的 `AGENTS.md`；无需把 Claude 会话伪装成 DSH 会话。
