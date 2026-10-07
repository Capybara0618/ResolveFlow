# Harness：真实崩溃恢复与strict回放

2026-10-07。三个窗口各5对，共15对、30次实际进程os._exit(73)、30次新进程续跑；生产AgentScope2.0.8/DurableRun/PG租约与fence，真实deepseek-flash usage。固定同一个A01A未发货业务场景、dense检索B；独立实验run/case保持相同业务事实，不是15种业务情形。GET接线到冻结合成源，不执行退款。

| 中断窗口 | 从头新增请求 | 恢复新增请求 | 减少 | post总token降幅 | 两组完成 |
| --- | --- | --- | --- | --- | --- |
| 模型返回但未保存 | 21 | 20 | 1（4.76%） | 7.49% | 各5/5 |
| 模型结果已保存 | 20 | 16 | 4（20%） | 13.16% | 各5/5 |
| 工具结果已保存 | 20 | 15 | 5（25%） | 16.32% | 各5/5 |
| 三窗口合计 | 61 | 51 | 10（16.39%） | 12.21% | 各15/15 |

仅计算中断后新增调用，平均每对减少0.667次。整体input token94684→83513（减少11.80%），output7253→5973（减少17.65%），total101937→89486（减少12.21%）；HTTP读取31→26。中断前两组各15次真实请求，input各15795，output从头1492/恢复1524；全部142次正式请求usage已取得，未知0，不混入恢复收益。平均续跑调查耗时从头16.049秒、恢复14.393秒，不包括子进程加载/索引构建启动时间。

未保存模型窗口两组都需重发。那1次请求差和token差来自真实模型路径波动，不能解释成未保存响应也能保证复用。结果已保存窗口1对恢复又多了一步读取（4 vs4），其余每对3 vs4；工具已保存窗口5对均3 vs4、HTTP1 vs2。temperature=0仍有自然响应差异，独立run的前置响应并非字节相同；报告是本轮真实观测，不承诺所有任务固定节省比例。

## 机制与质量核对

- 三个实际故障点由现有DurableRun hook触发，真实新进程接管；父进程只让自己实验租约过期。恢复复用已提交模型/工具journal，fence从1到2。模型未保存则只能重发。
- 从头执行组在自己的实验schema内取消原实验run（原journal保留），开新的隔离run，继承原active_deadline和前置已花预算；不拷贝模型/工具结果，不修改生产run预算规则。两组各自原120秒deadline在中断前后完全一致（30/30），不是把两个不同开始时间的run设置成同一绝对时间。
- [results](formal-v1/results.json)包含before/after预算、deadline、退出码、续跑数量；[summary](summary.json)按每对及窗口复算。所有30条续跑自动联合通过。Codex逐条核对终局摘要与P2引用：paid32900、NOT_SHIPPED、无占用、R-UNSHIPPED-001，均合理REFUND建议、商家审批，不产生授权；30/30有效（NONBLIND工程复核）。
- 正式前mock跨进程测试[JUnit](mock-junit.xml)26 passed/0失败/0跳过，包括15个新进程窗口及manifest/fence/retry/timeout路径。命令：设置RESOLVEFLOW_AGENT_DB到既有55433 PG后 `python -m pytest agent/tests/integration/test_c09_acceptance.py -q --junitxml=...`。
- 本轮重新执行当前strict18条，18/18 MATCH：[报告](strict-v1.json)。Python生产源码与锁未改变，复用当前代码已绑定的18包，不伪造新导出版本；业务输入分叉里的旧5包仅历史谱系，不是本轮18条成绩。严格处理记录再核对动作/引用/终态，包含预期FAILED轨迹，不要求每条业务成功。
- 缺模型记录、篡改状态版本、pack hash、缺字段和实际socket禁网：`python -m pytest agent/tests/unit/test_replay_pack.py agent/tests/integration/test_strict_replay.py -q` 最终[JUnit-v2](replay-negative-tests-v2.xml)4 passed/0 skipped；首次误设AGENT_DATABASE_URL致3pass/1skip，[原JUnit](replay-negative-tests.xml)保留，改为实际RESOLVEFLOW_AGENT_DB后通过。未另跑Docker OS网络隔离测试，不将Python guard结果称为本轮OS验证。

## 接线试跑与复算

trial-v1缺材料refs、trial-v2调用者buyer绑定错误，均在首个故障prefix前拒绝，无正式成绩；目录保留但无可汇总结果。trial-v3改为EVAL-BUYER后，未同步新的case wire identity导致SOURCE_MISMATCH，after-tool窗口未达到，所有失败原记录保留在[trial-v3](trial-v3/results.json)。修正只在实验深拷贝中将case_id/evidence.case_id绑定本次run；材料原文/hash与业务事实不改，生产工具权限未放宽。[trial-v4](trial-v4/results.json)六次崩溃/续跑全通过，随后冻结正式脚本。

正式命令 `python scripts/resume_recovery_benchmark.py --output reports/resume-quantification-v1/recovery/formal-v1`，密钥从既有环境变量读取；不覆盖既有目录、不重置共享累计usage账本。`python scripts/resume_recovery_summary.py` 无模型/网络，断言15对、30次73退出、deadline及sourcehash，聚合真实usage；Ruff通过。前置/续跑每条原prompt、P2、usage、HTTP、终局与轨迹全部保留。隔离实验PG schema按既有environment释放，未清业务schema。

简历可写：“在3类中断窗口的15组真实模型对照中，持久恢复使续跑模型请求减少16.4%、token减少12.2%；18条strict离线回放全部匹配。”
