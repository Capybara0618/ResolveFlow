# 客服共同边界修复证据

2026-10-24，依据[本批方案](../../docs/customer-agent-boundary-v1.md)。原[44轮评测](../customer-current-evaluation-v1/README.md)保留；本目录记录新工程行为，不覆写原模型答案或算成新模型成绩。

## A：理解前的真实应用上下文

- 原因：get_support_guide只在部分已接受意图后自动读取；理解之前不具备指南，stage.project还会剥离所有Observation。只提前调用工具、不改实际投影，模型依然看不到。
- 实现：仅orchestrated-v1在驱动前读取原指南一次，经原预算/journal；理解投影仅恢复已核对GUIDE原文，application_context分开可信当前对象、默认对象及是否有单。提示明确隐私/共享/接续属于GUIDE、退款政策条件属于POLICY；没有关键词路由或固定业务工具路径。
- 新测试最初5失败，见[红测](application-red.txt)。初实现2失败/29通过，暴露stage剥离；补实际Observation后另一字面JSON空白断言失败，改解析实际发送JSON后，三文件31通过，见[最终](application-tests.txt)。原纯政策测试仅更新新增公共本地读预期，保留无订单/物流和相关政策引用断言。
- 命令：根目录`PYTHONPATH=仓库根`、`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_application_context.py agent/tests/unit/test_support_orchestrated_engine.py agent/tests/unit/test_support_orchestration.py -q --tb=short`。agent目录Ruff上述三源码/两测试通过，strict mypy三源码通过。首次从根目录指定Ruff配置造成两个测试导入分组诊断，切agent目录按实际配置检查通过，未改变业务。保留Starlette既有弃用警告。
- `docker ps`失败：Docker Desktop LinuxEngine管道不存在；本步未运行PG/API恢复或Java/Web集成，不把skip算通过。单元中的真实SDK循环与脚本模型不等于真实模型语义改善。新增Provider调用0，账本2274；原四脏文件/旧报告保持，未重启正常项目或修改业务数据。
- 代价：即使纯政策也多一次本地指南读取及上下文，模型请求数不增加。范围为“理解前资料可用/可信对象有区别”，不是保证模型会选对。B的解释/步骤/正文合同仍按方案实施，当前任务进度只见todo顶部。

## B：目标驱动步骤，解释与最终正文保持

- 原因：compose按intent装操作，发布又按页面词要求next_steps；EXPLAIN下提到“售后咨询”会失败，HANDOFF/EXPLAIN却被强制附步骤。guide_only按引用只有GUIDE便清空text，误删“目前没有提交记录”等直接回答。
- 实现：Orchestration.required_actions按已接受goal与生命周期统一生成实际操作；EXPLAIN不生成申请或人工动作。program_owned限定当前编排，允许已读受控指南支持页面解释，程序只补该真实指南引用、不凭空造来源；直接跨页错配仍拒绝。当前编排保留原text再追加必要步骤，旧single/staged兼容模式的规则保持。退款/人工原因及原资金、事实、失效来源校验均保留。
- [6项红测](explanation-red.txt)→[76项针对回归](explanation-tests.txt)通过，包含新/旧导航模式和操作限制。随后50文件[429项客服与契约单元](support-unit-tests.txt)/[JUnit](support-unit-tests.xml)通过；另补流式直接解释保留与离线诊断9项[针对确认](final-targeted-tests.txt)通过，重叠不累加。Ruff四源码、相关测试/诊断脚本通过，strict mypy四源码通过；全仓/Java/Web未运行。

## 原真实候选的离线诊断

命令：`agent/.venv/Scripts/python.exe scripts/diagnose_support_boundary_v1.py --output reports/customer-agent-boundary-v1/offline-candidates-v2.json`。固定D03/1、D06/2、D08/1、D10/2，原模型决策逐字复用、来源取原保存工具结果；只有执行deadline更新，原本没读指南的D10明确新增当前公开指南输入。HTTP与外部socket拒绝，Windows asyncio内部loopback保留；这不是OS隔离strict回放或新模型生成。

| 原候选 | 原技术状态 | 新代码离线发布 | 直接解释 |
| --- | --- | --- | --- |
| D03/1 签收争议及后续方式 | FAILED | 通过，0修正 | 原候选保留 |
| D06/2 说找人工是否已转交 | SUCCEEDED，但正文被替换 | 通过，0修正 | “目前没有已提交核查记录”等原解释保留 |
| D08/1 已解决后接续原单 | FAILED | 通过，0修正 | 原候选保留，无新增申请摘要 |
| D10/2 物流不可用不等于丢失 | FAILED | 通过，0修正 | 不可用说明保留，仍按真实失败状态发布 |

[完整离线结果](offline-candidates-v2.json)只证明发布/呈现路径，不重新评判这些文字语义、不更新原44轮37/44或27/44，不宣称新增真实成功。原候选可能仍有冗长、重复建议等质量问题，不能仅因能发布算业务完整通过。

过程失败保留：[首次诊断](offline-candidates.json)4项失败，原因是socket.connect全禁连Windows事件循环内部socketpair也阻断，不是业务失败；改为拒绝HTTP/外部socket、允许内部loopback后另写v2。首轮扩大单元误设PYTHONPATH导致两个脚本导入错误，[记录](support-unit-collection-error.txt)保留；显式仓库根后429项通过。诊断脚本首次Ruff闭包绑定提示已修正，未改原数据或输出。

## Docker恢复后的真实PG/API/流式恢复

用户启动Docker后，实际没有业务容器运行。本批仅核实并启动已有resolveflow-review-demo-postgres-1（Compose project/service匹配，127.0.0.1:55433）；没有启动Java、正常Agent或模型worker。

根目录配置`PYTHONPATH=仓库根`、`RESOLVEFLOW_AGENT_DB=本机55433的agent_db`后，执行`python -m pytest agent/tests/integration/test_support_orchestrated_runtime.py agent/tests/integration/test_support_staged_api.py agent/tests/integration/test_support_stream_runtime.py agent/tests/integration/test_support_store.py -q --tb=short`：[18通过、0跳过](runtime-tests.txt)/[JUnit](runtime-tests.xml)。模型为脚本/合成Provider SSE，PG、API、fence及journal真实；不是DeepSeek或Java/Web整栈。

另在原恢复测试追加PG实际第一条tool记录和第一条model请求断言：[1项聚焦确认](persisted-first-context-tests.txt)通过，已包含上面18的同一测试，不累加。首模型UNDERSTAND实际持久请求有指南正文/O1；恢复同run新增模型/来源读取0；完成旧结果可复用，不完整manifest改变仍拒绝。

公共11表及schema测试前后摘要、旧评测hash/历史四脏文件/账本保护与运行资源收尾见[最终审计](final-audit.json)。本批新增Provider调用0，无Case/退款/模拟付款或正式业务写入；测试仅临时schema迁移/写入并清理。新代码已实现并验证工程链路，尚未进行新版本真实模型采纳或网页展示验收，不能宣称客服质量冻结。

审计确认11公共表摘要及schema集合相同、188份基线历史报告hash保持；测试专用临时schema已清理。仅停止本批启动且归属核实的PG容器，卷保留，Docker Desktop保持运行；未启动其他业务组件。A暂存红测输出曾触发一行pytest尾空白，规范本批新文本行尾后检查通过；未改历史冻结文件。
