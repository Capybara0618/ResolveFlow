# DSH 审查员优化执行手册

2026-09-29编制；代码核查基线 `928ec84`。这是用户批准路线的细化，不是第二份进度账本。实际进度只更新 `tasks/todo.md` 顶部。

## 1. 给执行者的任务

你负责执行剩余第二、三、四、五批。审查员的工作流是：看原始信息 → 核对 Agent 建议与依据 → 审批 → 查看结果。第一批核验/补证后的重新调查闭环已经实现，不重新迁移框架或重做第一批。

阅读顺序：根 `AGENTS.md` → `README.md`、`docs/core-scope.md` → `tasks/todo.md` 顶部、`tasks/handoff-current.md` → 本手册 → 当前一批文件。`docs/reviewer-optimization.md` 是设计依据，`tasks/plan.md` 保留原路线。旧 CXX、AS、迁移交接仅按需查历史，不是执行命令。

| 顺序 | 当前批说明 | 必须交付 |
| --- | --- | --- |
| 第二批 | [02-demo-chain.md](02-demo-chain.md) | 修正5个已知契约失败；隔离的mock整链路；可恢复的六类稳定样本 |
| 第三批 | [03-readable-sources.md](03-readable-sources.md) | 引用精确定位、业务字段可读、条件/例外可核对 |
| 第四批 | [04-agent-rag.md](04-agent-rag.md) | 五个难例的离线诊断及必要修复；真实模型验证单独记录授权与状态 |
| 第五批 | [05-fields-visual.md](05-fields-visual.md) | 商品展示字段贯通；正式审查员页面视觉和交互收口 |

严格按顺序推进。每批内部按文档子步实施，通常每子步3–5个核心文件；按功能批次集中运行相关验证，不每改一个文件就全仓测试或询问用户。可先写关键失败测试来定位缺口；整批通过后精确commit/push，再进入下一批。只有第四批的付费live验证可以独立待授权，离线部分通过后允许继续第五批，不能把live标为通过。

## 2. 接管与保护

1. 本次交接只编写文档，不启动DSH、不启动执行模型，不代表业务应用已切换为任何DeepSeek模型。DS作为编码执行者与项目内Agent使用的模型是两件事。
2. 以交接者最终明确“已停止写入”作为接管点。接管先检查实时git和进程，确认没有其他业务写入者。同文件新增不明改动时暂停该文件，不能覆盖、stash、reset或清工作区。
3. 在 `E:/Code/Agent+Backend` 执行；确认仍为 `main` 跟踪 `origin/main`、origin为 `https://github.com/Capybara0618/ResolveFlow.git`。基线SHA是定位信息，不允许强制回退到它。
4. 原有未提交内容见 `tasks/handoff-current.md`。特别是 `docs/engineering.md`、`scripts/verify.ps1`、`scripts/verify.sh`、Commerce的 `RefundAcceptanceApiTest.java`，以及旧reports日志/SQLite，不能夹带提交。遇到必要依赖先审阅其差异，不能直接据为本批成果。
5. 不安装/升级锁定依赖，不更换框架，不重新规划四批。允许局部函数拆分、类型收窄、错误处理和必要的追加迁移。核心协议、状态语义按本手册及领域规范落实，不能凭截图推导业务规则。
6. 保留所有现有工单、数据库和卷；新演示数据采用隔离实例/命名空间并持久保存。不清库，不执行 `docker compose down -v`，不按端口杀未知进程。

## 3. 不可突破的条件

- 单订单行、全部数量、CNY整数分、全量模拟退款；不新增部分退款、补发、库存、真实支付、媒体上传、客户画像或审批额度。
- 同订单行最多一次成功；已退加预留不超过实付；UNKNOWN保持占用、原operation/provider ID，不能换ID再付。
- 已消费授权冻结输入；四个旧入口（材料、核验、人工方案、取消）仍必须拒绝。不得通过“退回待审”解除冻结。
- Java拥有工单、金额、授权；Python拥有run；新修订可建新run，同run恢复不能重置预算/deadline、换manifest或绕过fence。
- 唯一生产循环仍为AgentScope 2.0.8；mock脚本不能进入生产业务判断。Agent没有审批、退款、政策写入或跨主体读取权限。
- 原始正文、Agent整理、推断、人工核验、Java校验分开。不能把模型置信度/相似度变成授权，不能伪造绿勾、媒体真实性、客户资料或资金状态。
- 历史工具结果来自保存记录；不拿当前订单/物流替换历史依据。引用必须匹配完整身份、版本及hash；主体权限由服务端检查。
- 不调用新收费模型，不沿用旧C12预算；不公网部署，不新增付费资源。无需为普通范围内实现反复询问。

## 4. 工作方式和偏差处理

先读入口源码和已有测试，判断“已实现/有缺口/环境不可用”。已实现且有证据的能力复用；只补缺口。文档指定的文件是入口，不要求机械修改每一个。

| 发现 | 允许动作 | 禁止动作 |
| --- | --- | --- |
| 类/路径轻微变化 | `rg`定位相同职责，报告实际路径 | 为匹配手册另造同功能模块 |
| 类型、局部兼容错误 | 同步生产者/消费者/fixture后重跑受影响测试 | 删除字段校验、放宽未知字段校验 |
| 测试失败 | 保留错误，分类为新增/已知/环境；修复本批新增失败 | 删除断言、skip/xfail、调大容错掩盖逻辑错误 |
| 原服务端状态不支持期望动作 | 先核对domain-model和已有服务，报告证据 | 前端伪造状态，SQL直接造授权/方案/成功事件 |
| 外部环境不可用 | 完成可独立的离线实现并记录未运行，停止依赖项 | 写“通过”、无界轮询、自动打开live兜底 |
| 金额/权限/fence边界必须改才可继续 | 停止相关工作包，写最小复现和建议，交用户决策 | 自行扩大权限或重构资金核心 |
| push失败或并行写入不明 | 保留本地成果、报告SHA/错误，暂停后续业务写入 | force push、自动改remote、重写历史 |

每批末报告具体行为、命令、实际数量、失败/未运行、样本与模式、改动文件。报告只记证据，不另建进度看板。不为文档措辞改动运行整套业务测试。

## 5. 基础命令与测试约定

以下为现有命令，PowerShell，工作目录为仓库根；不把未来脚本当现有可执行命令。

```powershell
git status --short
git branch --show-current
git remote -v
git diff --name-only
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
docker compose -f infra/compose.yaml ps
pnpm --dir web test
pnpm --dir web build
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_openapi.py -q
git diff --check
```

Java按当前批给定类名运行，`-Dsurefire.failIfNoSpecifiedTests=false`只为聚合模块无所选类；必须核对case/commerce目标实际执行的类及计数，零项不是通过。

Python集成测试的 `agent_db` 使用独立临时schema；数据库不可达会skip，skip要算未验证。`RESOLVEFLOW_AGENT_DB`只指定测试/演示对应PG连接，不打印凭证。`stub_embedder`证明过滤/接线，不能当真实dense质量结果。

每批验证后：精确 `git add -- <本批清单>` → `git diff --cached`、`git diff --cached --check` → commit → fetch并核对待推送范围 → 普通push →核对远端包含提交。禁止 `git add .`，遵循 `docs/engineering.md` 第8节。推送仅在remote/upstream仍核实无误时执行。

## 6. 完成的定义

四批完成必须同时提供：可反复打开的合成样本、至少一条真实服务的mock人工审批退款链路、UNKNOWN幂等证据、引用定位与权限用例、难例逐条记录、正式页面多视口截图和功能验证。文档、stub单测或静态预览均不能替代相应实际验收。

未获live授权时准确表述“工程与离线部分完成，真实模型质量待验证”，不能声称Agent真实质量提高。某批集中验收失败就不要勾该批完成；已知5个契约失败必须在第二批修掉，不能长期作为豁免。

## 7. 可直接粘贴给DSH的开工提示词

> 在 E:/Code/Agent+Backend 接管审查员优化。先只读核查 AGENTS.md、README.md、docs/core-scope.md、tasks/todo.md 顶部、tasks/handoff-current.md、tasks/plan.md、tasks/dsh-reviewer/README.md，然后执行 tasks/dsh-reviewer/02-demo-chain.md。第一批闭环已完成，不重做；剩余四批按02→03→04→05顺序实施。你是执行者，遵守手册指定范围、数据所有权和验收条件；不另起架构、不恢复CXX/C12、不改锁、不启动多Agent。每批集中验证、写证据、更新唯一账本、精确commit并正常push后继续下一批，不每小步要求用户验收。保留既有脏文件和数据库；未授权收费live只记待验证，不阻塞可独立离线与视觉工作。读取当前交接的停止写入说明并检查并行编辑，遇到业务范围冲突、资金/权限风险或推送失败按手册停止相关工作并报告。
