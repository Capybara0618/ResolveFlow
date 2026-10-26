# Harness/上下文评测准备记录

2026-10-26。本批完成原始材料、评分口径、raw上下文对照、跨检查点状态接线及脚本SDK验证；真实模型与真实PG故障驱动仍待接入。没有新效果指标，不改生产/简历/旧结果。

## 固定输入与入口

- [协议](../../docs/customer-harness-context-v1.md)：16段×2检查点×2组=64回答轮；5恢复任务×3窗口=15配对。四家族各含0/8/24/48组背景，短上下文控制单独保留。
- [原始材料及rubric](../../evals/customer-harness-context-v1/cases.json)：作者合成、非盲测/非holdout；不是商用用户记录。
- [准备审计](preparation.json)：54文件hash，含现有support/harness源码、tokenizer、锁、本批规格/脚本/测试/数据。64脚本SDK回答轮均完成，每轮2次脚本决策，共128次本地mock决策；semantic_quality及provider_usage明确为null。
- [适配/基线](../../scripts/evaluation/customer_harness_context_v1.py)：仅prepare/check，无live/execute入口。对照复用同一生产AgentScope循环、阶段、预算、权限和答案检查；只改变跨轮状态及历史呈现方式。raw按实际阶段请求预算逐条移除最早原文，不提前固定一个更小窗口。

第一检查点实际结果进入本组下一检查点；layered状态只从生产引擎实际接受的回答/conversation_update导入，不读取rubric创建记忆。raw历史保留自己的实际回答，工具/历史可读权限未收紧。两组模型选择不同动作的成本与失败将如实保留，不能拿脚本固定两步推断真实调用数量。

## 实际验证和失败

1. 先新增关键测试，实际pytest因评测模块不存在收集失败；补实现后9项通过。覆盖矩阵、Gold输入隔离、无前缀不得第二检查点、错误会话前缀拒绝、相同provider预算、基线按时间保留原文、必要字段超限0模型、实际SDK循环、禁止导入伪造的跨轮结构化状态，以及当前Journal STARTED/COMPLETE合同。
2. 初次64轮脚本接线在第二个layered检查点失败INVALID_DECISION：脚本对已存在事项仍发送ADD。修正脚本按实际previous_tasks使用CONTINUE；没有放宽生产校验。该次在任何最终输出写入前退出，没有质量分数或真实模型请求。
3. 两文件Ruff最初导入顺序/字符串拼接风格4项，修正后通过。随后prepare完成64脚本轮，再check核对材料及54文件hash通过。已有Starlette/anyio弃用警告保留。
4. 集中回归新9项及既有上下文/陈述记忆测试，共[32项通过](tests.xml)、0失败/0跳过；未扩大到Java或全仓库测试。真实用量累计账本仍为3289，本批没有新收费请求。

实际命令（PYTHONPATH包含仓库/agent/src/agent，PYTHONIOENCODING=utf-8）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_customer_harness_context_v1.py -q
agent/.venv/Scripts/python.exe -m ruff check scripts/evaluation/customer_harness_context_v1.py agent/tests/unit/test_customer_harness_context_v1.py
agent/.venv/Scripts/python.exe -m scripts.evaluation.customer_harness_context_v1 prepare
agent/.venv/Scripts/python.exe -m scripts.evaluation.customer_harness_context_v1 check
```

## 已确认的恢复边界和未运行

源码和直接调用Journal的无数据库桩验证：当前模型STARTED恢复抛UNKNOWN_MODEL_RESULT，COMPLETE才返回已存响应。旧调查DurableRun的16.4%不能直接当作新客服成绩。恢复三窗口要分列，模型未保存窗口现不预设完成，不能把未知调用失败造成的少请求当收益。

本批没有真实provider/付费请求，没有访问或启动业务数据库/Java/网页，没有进程崩溃实验，没有新strict回放。`docker ps`只读检查未显示运行中容器；未启动容器。PG持久化/真实退出/fence仍须下一步验证，不能用这里的桩冒充真实恢复。

下一步先实现逐轮真实请求计量/写入与SupportStore进程故障驱动，以无网络桩和隔离PG验证；根据执行路径确定收费发送上限与累计起点后再运行真实模型。不自动调用付费API、不改原Agent/RAG或简历，也不为得到旧16.4%修改生产恢复语义。

## 后续接线完成记录（2026-10-26）

计量/故障实现c3aaf9c正常push后，已完成[集中验证](wiring-v1/README.md)：12计量/PG检查，64上下文轮/128本地SSE发送，30真实进程退出/30接续。10已保存窗口恢复完成，5未保存窗口明确UNKNOWN_MODEL_RESULT，15从头对照完成；均为脚本合同验证，不能当作模型效果。public/schema/输入hash及原4脏文件/累计收费3289保持，独立65433测试PG已恢复停止。原preparation.json及54文件hash不改；正式模型共享账本/上限/入口和源审仍待接入。
