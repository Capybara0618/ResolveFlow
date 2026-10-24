# 独立事实合并读取与首正文关键路径

2026-10-24，用户批准继续Agent质量与速度收口。上一工程步`6c2e3c1`已普通push核实后，按[开发说明](../../docs/customer-agent-fact-batch-v1.md)实现模型选择的READ_FACTS。

## 分析与实现

[旧网页关键路径](critical-path.json)来自上批真实记录：接受到首正文6488.443ms，GUIDE/ORDER/SHIPMENT/POLICY活动合计322.577ms，其余6165.866ms包含模型、网络、SDK、上下文、journal及调度。不能当纯供应商推理耗时，也不能把RAG约26ms当整段等待。

当前事项同时缺订单和物流时，模型可选择READ_FACTS一次声明两个绑定只读工具；程序经原SDK按声明顺序逐项执行，每项保留预算、fence、独立journal、来源失败与activity。只缺一项、其他工具/主体/参数、重复工具不接受；单读继续可用。不是并行工具调用，不在程序中按意图预设整条调查路径。

## 实际验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 失败先行 | 新12例5失败/7通过；旧实现不能合并 | [red.txt](red.txt) |
| 针对SDK回归 | 合并/政策/编排/目标核对43通过 | [targeted.txt](targeted.txt) |
| 客服单元及合同 | 同上一批命令，增加12例，494通过0跳过 | [unit.txt](unit.txt) |
| 真PG/API/流式与恢复 | batch、refund_policy、goal_review、orchestrated、summary_grounding、stream六文件，14通过0跳过 | [首轮12项](runtime.txt)、[最终14项](runtime-final.txt) |
| 静态 | 3源码strict mypy、3源码2测试Ruff通过；新增PG测试首次未使用pytest已通过增加fence测试解决 | [static.txt](static.txt) |

同证据脚本单读5模型请求、合并4，工具预算均2、本地读均2，保留事实/政策引用、原话摘要和最终流式正文；反序也成立。完整PG恢复0新发送；第一项完成/第二项开始前中断后，第一项复用、后两模型和剩余工具接续，总模型预算4/业务工具2不重置；已STARTED无结果明确中断不重发，fence失效后第二项不执行。

本步没有新的真实供应商请求（usage2349），不能把脚本5→4写成真实耗时改善、模型采用率或简历指标。旧真实4/5及原网页6.49秒保持；政策Query和语义判断仍由模型负责。本步未做Java/Web构建或浏览器确认，未修改RAG排名。保护审计见[audit.json](audit.json)。

下一步按冻结新输入做有限真实验收，分别判断政策解释、合并采用及实际首正文；不改旧失败或为未通过题追加收费重跑。浏览器控制未恢复，刷新/渐进DOM和截图仍未完成。
