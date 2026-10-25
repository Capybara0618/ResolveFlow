# 独立 Workflow 对照：设计与离线准备

2026-10-25，用户要求开始设计，独立基础Workflow不得借用现有Agent内部模块。本轮完成[可执行规格](../../docs/customer-workflow-comparison-v2.md)、[32场景/50输入的对外判据](../../evals/customer-workflow-comparison-v2/cases.json)及[离线审计/源审模板/主指标汇总入口](../../scripts/customer_workflow_comparison_prepare.py)。基线业务实现、真实执行器和Agent修复尚未做；没有正式效果分数。

主对照是完整客服Agent与“原始历史→LLM路由→固定分支→LLM回答/摘要”的独立Workflow。只共用模型API、主体绑定、订单/物流/政策/指南原始接口和中性测量设施；不共用理解、事项、记忆、Harness、来源就绪、摘要装配或生产提示词。普通分支覆盖ORDER/LOGISTICS/QUALITY/POLICY/REFUND/HANDOFF/GUIDE及OTHER，必须先实际可用；最终回答允许覆盖已有依据支持的多个问题。

主指标是24个复杂模拟售后场景的完整处理成功率，普通8个和总体32个分别列出；首次仅一轮配对，64会话/100客服轮。模型/工具/时间成本辅助报告，不预先承诺每项都优于基线。相同客户原话和事实，输出改用对外业务判据；不检查Agent专用状态。Q25条件句允许解释假设，不强制查询，两边同标准。旧v1负向结果保持，新比较不能与旧分数拼接；不是独立盲测。

实际命令（仓库根，现有agent/.venv，PYTHONPATH为仓库及agent/src）：

```powershell
python -m scripts.customer_workflow_comparison_prepare audit --output reports/customer-workflow-comparison-v2/design-audit.json
python -m pytest agent/tests/unit/test_customer_workflow_comparison_prepare.py -q
python -m ruff check scripts/customer_workflow_comparison_prepare.py agent/tests/unit/test_customer_workflow_comparison_prepare.py
```

[数据审计](design-audit.json)通过：32场景、24复杂、50原输入、源快照/顺序/故障覆盖与v1相同。10项离线检查通过，Ruff通过。首次9项中空格摘要被误当存在（1失败/8通过），补为非空文本后9通过；随后新增旧协议/异数据身份检查，最终10通过。脚本数据只证明准备/评分器接线，不是Workflow或Agent质量。

已验证：无需task_state/记忆标记也可按相同业务结果评分；缺摘要、错误操作摘要、技术失败勾全通过、未审、缺结果、身份不符均拒绝；失败成本/超时/NOT_RUN保留分母，任一轮失败整会话未完成。源审依赖Codex读取原话/实际来源与回答，不按关键词自动判语义。

后续中性runtime文件准备好后可运行`review-template --runtime 新文件 --output 新源审.json`，填三项检查/evidence后运行`summarize --runtime 新文件 --review 新源审.json --output 新汇总.json`。CLI绑定完整runtime字节hash，输出拒绝覆盖。主指标汇总已实现；耗时分位数、真实usage/未知usage、双方均完成的调用配对分析由后续执行/报告接线完成，不假称本轮已测量。

下一实施步是独立基线及其普通分支/异常出口/草稿的离线接线验收；随后另做Agent通用缺口修复和双组执行器。待实现固定后再生成执行manifest，不能把设计审计称为正式冻结。预计约250模型请求、建议上限400仅作后续计划，当前未发送且未授权执行本批测量。

本轮新供应商/本地模型推理0，ledger3053保持；未访问业务数据库、未启停服务、未改生产/简历。旧报告、旧manifest/数据、四历史脏文件保持，保留核验见[本轮审计](preservation-audit.json)。现有RAG正式结果独立保留，不因新Agent基线自动重测。

## 独立控制器实现（2026-10-25接续）

独立模块scripts/evaluation/basic_customer_workflow.py已实现：八类单意图路由、固定读取、一次公共GUIDE、最多两次模型常规调用、每阶段一次格式修正、瞬态源失败重试一次及最终失败说明、直接模型草稿输出。无跨轮结构化状态、无自选追加工具、无Agent继承/生产提示/grounding/确定性摘要装配；导入隔离检查只允许标准库与pydantic。按主体读取的客户端仍由后续中性服务提供，控制器本身不持有业务写入口。

实际`pytest agent/tests/unit/test_basic_customer_workflow.py agent/tests/unit/test_customer_workflow_comparison_prepare.py -q`为27通过（17基线+10准备），四文件Ruff通过。先测试确认模块缺失的收集错误，落实现后全部通过；首次Ruff的导入/行长及异常边界说明已修。覆盖八分支、草稿原样保留/不补写缺稿、503两次原始结果进回答、404不重试/不拿标价代实付、最近20条原始历史/过滤Gold及Agent状态、格式修正不重新取证、模型不能追加工具、预算/超时停止、异常调用的未知usage留痕。

[八分支脚本接线](basic-workflow-offline.json)及[当前准备审计](baseline-audit.json)已生成，全部mode=scripted，不是业务质量分数或真实分类成功率。一次命令把烟测代码传给audit模块的stdin，实际只执行审计；已用独立Python stdin入口真正运行八分支并保存输出，未产生供应商请求。普通首正文尚未独立流式计时，first_body_ms=null/NOT_MEASURED，不填0。

本步0新供应商/本地推理、ledger3053；无DB或服务启停、无生产/简历改动。真实模型客户端、共享原始接口/两组历史驱动及性能聚合仍待接线；Agent通用缺口接下一小步。设计阶段design-audit/preservation-audit保留原时间状态，不回写为已经实现。
