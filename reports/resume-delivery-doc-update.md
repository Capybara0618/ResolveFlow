# 简历导向交接完善记录

日期：2026-09-26。范围：仅文档与只读检查；未改业务代码、测试、数据库、依赖或部署配置，未提交/推送，未调用付费模型。

## 变更

- `tasks/todo.md`：按源码与有限复验修正顶部C08快照，保持整包未完成；C11.2细化a–e，C12复用测量证据，C13审计候选主张。
- `tasks/handoff-current.md`：标记阶段记录为历史，撤销固定从C08.1a开始的提示词，开工统一读todo顶部；要求保留已有代码并先核实实际进度。
- `docs/core-scope.md`：移除仍要求先做AS00/AS01的过期起点，转向唯一账本；业务范围和验收不变。
- `tasks/plan.md`：补充证据导向和检查点，不增加工作包、整体重构或实验矩阵。
- `docs/evaluation.md`：细化单查询SQL/Redis测量、公平基线、数据隔离与有界回源的证据口径，不改原实验规模。
- `docs/resume-evidence.md`：六个简历展示方向映射原K1–K7及C任务、代码/测试/演示/限制；增加证据卡格式，规划不当成果。

## 状态核查与真实验证

源码核查发现：`AskQuestion.field`已必填，PROPOSE缺`case_type`已拒绝，比C08.2-7历史记录靠前；工厂要求显式mock/live，不是默认mock。runtime中未找到`verify_proposal()`调用，API入口未找到`RunWorker/build_investigation`装配，不能声称完整闭环或持久恢复通过。

以下命令均在 `E:/Code/Agent+Backend/agent` 实际运行，未修改这些测试或实现：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_callback_payloads_match_the_case_contract.py tests/unit/test_proposal_verifier.py tests/unit/test_harness_manifest.py -q -p no:cacheprovider --tb=short
# 27 passed in 1.50s
.\.venv\Scripts\python.exe -m pytest tests/unit/test_harness_loop.py -q -p no:cacheprovider --tb=short
# 31 passed in 1.63s
```

合计58项针对性离线单元测试通过。并非全量回归、真实模型、MCP子进程、Java/数据库/MQ集成或H1–H5验收；本轮没有重跑Ruff/mypy和all-offline，不引用旧数量宣称新状态全绿。现有测试注释仍有“Skipped”的历史文字，实际四种载荷测试已执行；本轮不顺手改测试文件。

## 文档检查

编辑前两次读取5个目标文档SHA-256一致，未观察到这些文件并行变化；保留工作区全部既有源码、测试与报告修改。

- `git diff --check -- docs/core-scope.md docs/evaluation.md docs/resume-evidence.md tasks/plan.md tasks/todo.md`：通过。
- PowerShell对上述5份文档及`tasks/handoff-current.md`、本报告逐份检查本地Markdown链接、围栏配对、行尾空白：**7份文档、52个本地链接，全部通过**；不检查外网链接可用性。
- `rg -n 'C11.2[a-e]|简历导向|六个展示|查询/Redis对照' tasks/todo.md tasks/plan.md docs/resume-evidence.md docs/evaluation.md`及提示词末段人工复核：五子步、六方向映射、原依赖和测量口径一致；当前提示词不再从C08.1a起步。
- 文档补丁曾因上下文行不匹配失败，核实未落盘后以精确上下文重试成功；不涉及代码/测试失败。Git差异包含用户已有未提交文档修改，不能把相对HEAD的全部行数归成本轮成果。

## 下一步与边界

DSH按todo顶部收口C08尚缺回归/接入，再遵循原依赖推进。C09预算冲突仍须显式解决；恢复、strict与live不能用离线探针代替。C11.2落地真实SQL/Redis路径，C12报告实测结果，C13选择简历主张。没有新增商业用户、生产高可用或收益承诺。
