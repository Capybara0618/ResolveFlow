# 单场景真实政策追问确认（2026-10-23）

用户明确批准执行[原计划](../../evals/customer-policy-focus-v1/live-plan.json)：原追问只跑一次、至多12次模型请求，不强制子Query、不自动重跑，不作为简历指标。生产基线9b7700c。

## 固定输入与运行边界

[input.json](input.json)来自原第二轮真实验收的合成会话历史/旧事项，当前追问原文不变。订单、物流只读响应取原保存快照，明确不是本轮实时Java查询；本店政策使用原run绑定的真实本地PG generation和现有embedding。新run及调用账仅在自建临时schema，public全表前后校验，导出后仅删除本次schema。Java/Web不启动，不写当前客户会话/退款，不调整政策、Gold或原运行结果。

`SupportRuntime`→原AgentScope staged-v1→实际`StreamingLiveModelClient`子类执行，Provider为DeepSeek Flash、thinking禁用、JSON、temperature0，输出仍由原1024/step和12次/活动deadline约束。计数在发送前保存，实际请求/回应/Query/引用及失败全记录；流式客户端无内部重试。预热单列，Agent运行时间包含SDK/模型/检索/PG，不是网页首字或p95。

## 预跑

- 两个单元测试验证发送前记账、硬上限不多发、逐块正文观察、快照run绑定与未知读取404；真实PG/实际生产运行入口+合成Provider SSE端到端，3次合成模型请求全部在测试私有账/临时schema，验证导出/清理及public不变。
- `PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：单元+集成 **3通过、0跳过（14.72秒）**。Ruff首轮发现缺BoundSources导入/冗余noqa及测试导入/长行，修正后Ruff和py_compile通过；尚未发送真实请求。
- `scripts/confirm_policy_focus_live_v1.py prepare`：原policy generation就绪匹配，冻结[源码及输入SHA](manifest.json)，新增模型0。原账仍2022。

## 一次真实执行与审查

准备提交11a14a5普通推送并核实后，执行`agent/.venv/Scripts/python.exe scripts/confirm_policy_focus_live_v1.py execute`一次。真实模型3次（理解→检索决策→回答），无修复/重试，调用账2022→2025。运行正常终止`SUCCEEDED`，但**政策回答质量验收失败**。完整请求/响应/工具账见不可覆盖的[runtime-results.json](runtime-results.json)，逐项来源审查见[review.json](review.json)；不以运行状态代替回答质量。

| 原计划检查 | 结果 | 实际证据 |
| --- | --- | --- |
| Query补承接语境且不把历史当当前物流 | 部分达到 | Query带“物流运输中/延迟”，focus仍泛化为未收到货；终局仍断言当前状态 |
| 取得普通在途边界和承运商确认丢失条件 | 未通过 | top3仅未发货、损坏、签收争议，两条关键规则都未进入 |
| 回答聚焦当前问题 | 未通过 | 罗列上述三类退款，漏解释“继续在途”与“之后确认丢失”的条件分支 |
| 不编强制材料、不审批/建单 | 通过 | 明确政策未列清单、准备材料仅建议；只调用政策检索，无业务写动作 |
| 完整记录调用/失败/成本边界 | 通过 | 三次真实请求/usage及工具、私有运行导出保存，无自动重跑 |

模型自主选择单Query，未选择可选双分支；这本身不判错，原计划从未要求必须调用新能力。实际Query为：

> 未收到货（物流运输中/延迟）时店铺售后政策：处理条件、时限及需要客户提供的材料

本次仅1次`search_policy(top_k=3)`，依次返回`R-UNSHIPPED-001 / R-DMG-001 / R-SIGNED-001`。其后模型直接回答，没有再读取缺失政策。本轮`fact_view=[]`，没有订单/物流读取，引用也只有政策，却写出“您当前的情况是运输中且有延迟记录，尚未出现丢失或签收结论”。虽然它恰好与存档快照相符，依据仍来自旧助手发言，不能称本轮已核实事实。纯政策解释可不查物流；此处应保留“沿用上轮讨论背景/如果仍在运输中”的条件语义，不直接判定当前订单资格。

## 同一Query的只读定位

随后以PowerShell here-string交给`agent/.venv/Scripts/python.exe -`，复用`ReadOnlyDatabase/PolicyIndex/SupportEmbeddings/retrieve_policy`，在原merchant/manifest/generation上只执行该Query，诊断时把最终`top_k`从3改为5，其他检索逻辑不变。没有修改生产默认、原运行或答案，没有尝试其他改写，也没有新增LLM/HTTP调用。结果另存[exact-query-top5.json](exact-query-top5.json)，绑定原运行SHA及检索源码SHA：

| 排名 | 条款 |
| --- | --- |
| 1–3 | 未发货、损坏、签收争议，与真实工具前三完全一致 |
| 4 | `R-INTRANSIT-001` 普通在途 |
| 5 | `R-LOST-001` 承运商判定丢失 |

这证明相关文档确实存在于本次候选中，但当前Query+RRF排序将它们放在输出窗口之外；不能归因于文档缺失或索引没接通，也不能因此断言Query生成已做好。只把“运输中”加进长Query不足以纠正排序，相关主题覆盖没有被结果选择或后续决策保证。回答模型又按已命中的类别罗列，并把历史陈述当现状，形成第二个独立质量缺口。现有完整六条合成政策均未给出具体材料清单，本次“非强制建议”的处理方向正确。

## 用量、耗时与环境收尾

- Provider准确输入9191、输出489 tokens（逐次2309/117、2989/48、3893/324；均非估算）。Harness预留/估算输入10526另列，不与Provider实际用量混淆。
- 本次Agent运行6057.38ms，包含三次串行模型、检索/SDK/PG；权重/词法预热9355.03ms在计时外。第三次模型开始后764.43ms出现首个可投影正文，仅为该次模型相对时间，未测整轮/浏览器首正文。
- 只读top5诊断预热12797.52ms另列，检索单次90.71ms，非p50/p95，也非生产回答改善证明。
- 真实执行和诊断public表前后hash均保持；只删本次自建schema，调用账已导出，临时账锁释放。Java/Web未启，本次PG容器收尾停止、保留卷。原四脏文件及原清单/probe六个SHA逐一保持。
- 用Python对冻结输入/源码SHA、三次usage/账增量、工具结果/诊断前三一致性、空fact_view与无事实路径、原始结果hash及全部public表hash进行一致性检查，通过。新增仅证据/文档，无生产源码修改，不重复收费或整套回归。

## 后续修正方向

先用保存Query和响应离线比较候选覆盖/排序：以本店六条短政策的有界全读作为质量基线，与现有top3、候选扩展后相关性筛选比较。确定检索证据充分后，再处理回答聚焦与历史事实措辞，不能只把top_k增大或强制所有问题分支就称解决。无需据此重做两阶段AgentScope框架；本次也未证明换框架或增加Agent会有效。新真实确认另行限定输入/次数，不在本次失败后自动重复。本轮不进入R1–R3聊天退款或简历指标。
