# Claude Code → DeepSeek Harness 迁移交接

更新时间：2026-09-18。本文件只保存跨客户端继续工作所需的索引与迁移边界；项目事实、实现状态和验证证据仍以各自权威文件为准。

## 继续工作时的读取顺序

1. 根目录 `AGENTS.md`：长期实施约束与不可变规则。
2. `tasks/todo.md`：唯一进度账本、已完成项、验证结果和下一任务。
3. `docs/implementation-handoff.md` 与 `tasks/plan.md`：实施路径和依赖关系。
4. 当前任务涉及的专题规格、契约、源码和测试；不要用旧聊天覆盖工作区现状。
5. 只有在上述资料无法解释某项历史决定时，才查阅下方 Claude Code 原始档案。

## 迁移时的工作断点

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
