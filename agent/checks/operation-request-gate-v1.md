# 买家操作请求核对修复（2026-10-28）

## 问题与范围

上一轮真实验收保留在 [buyer-view-live-v1.md](buyer-view-live-v1.md)：买家问“现在应该找谁帮我”，规划阶段却选择 MERCHANT_REVIEW，最后生成核查摘要。原文出处校验通过，产物与错误目标也一致，所以旧 GoalReview 没有触发。此处缺少的是操作产物的准入检查，不能靠再补一句措辞提示或修改展示卡片来解决。

本批修复唯一生产 AgentScope 循环内的准入路径。没有增加 Agent、服务或 Java 写权限，没有修改前端协议、退款金额、本人确认、商家审批或旧历史消息。没有新付费模型请求、业务 HTTP/数据库写入；真实费用账本保持 3639。原真实失败和原始结果未覆盖。

## 实现

- 规划中的操作目标先作为候选；非 EXPLAIN 活跃目标必须进入 CHECK_REQUEST，不能直接调查、编译原因或输出动作。
- 该阶段只看本轮完整原文、必要历史与待核对原文片段，不展示规划器的 intent/goal、改写诉求、候选答案或系统事实，减少以规划结论为前提的重复确认。旧历史只用于消解指代。
- 独立输出 INFORMATION / PREPARE_REFUND / MERCHANT_REVIEW / UNCLEAR / DECLINED。只有核对用途与候选操作一致才放行；询问、假设、暂缓、含糊或动作不匹配降为 EXPLAIN，清除操作原话，不生成原因或动作。含问号和“先别发送”的明确准备请求仍可放行。
- 程序整批验证 task_id 完整唯一、当前原文出处；无效同批项目不会部分批准另一项。核对过的凭据绑定事项、目标及操作原话，不跨动作借用。
- 现有一次 GoalReview 之后如更改为另一操作或从解释升为操作，仍须通过准入核对。每批候选一次核对，全 run 最多两轮；使用原有调用数、deadline、journal、fence 与唯一 SDK 循环，不重置预算、不添加无界重试。
- 正文/原因仍经既有来源、金额和产物检查；CHECK_REQUEST 的内部理由不流式展示给买家。核对结果随后续模型请求保留在内部上下文，进入同一持久调用轨迹。
- manifest 标记 request-check-v1，纳入新模块和全部阶段提示 hash。completed 结果仍复用；在途版本不匹配明确拒绝，不静默迁移。

主要生产源码：`agent/src/resolveflow/support/{request_check,orchestration,orchestration_prompts,engine,service}.py`。

## 验证记录

先新增保存真实反例的两项检查再实现，实际得到 2 失败；新增门禁后通过。反例原三决策直接回放现在被挡住，未读业务事实、没有答复/操作产物；再提供脚本化 INFORMATION 核对及正常答复可完成回复，action/摘要均为空。

新增测试同时覆盖明确准备的两种操作、问号请求、假设、暂缓、含糊、动作不匹配、批次原子性、旧目标核对后再次准入、调用预算、内部理由不流出及 mock ABI。这里的用途判断为显式脚本输出，证明代码按核对结果执行，**不证明真实模型会正确判断这些中文表达**。

旧结构/来源/恢复测试使用 `tests/support_request_checks.py` 显式补充正向核对前提；该 helper 假定原脚本操作意图正确，禁止用于语义验收或真实驱动。旧真实记录本身未改。原模型次数/流式 attempt 序号按实际新增阶段更新，金额、来源、终止等断言保留。旧固定控制器及混合前缀比较的本地忽略资产 `scripts/evaluation/support_fixed_current.py`、`agent/tests/unit/test_support_fixed_current.py`、`agent/tests/unit/test_support_summary_live_driver.py` 同步适配新门禁，只为兼容检查，不改历史实验结果，也不作为新增真实费用或效果证据；不 force-add 这些旧本地资产，生产实现与新增测试均不依赖这些适配。

- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit -q -rs -k 'support or buyer_language_smoke' --tb=short --junitxml=tmp/request-check-unit-final.xml`：617 通过，8 个原无 citation 样本跳过，2044 未选；输出 `tmp/request-check-unit-final.log`。其中 15 项为新增准入检查。
- 首轮 PG 检查因默认端口 55432 未连通而跳过两项，不计通过。实际演示容器为 55433，后续用原 DEFAULT_DSN 仅替换端口，在进程内设置 RESOLVEFLOW_AGENT_DB 后执行隔离 schema 检查，结果见后续收口。
- 正确端口下 `pytest agent/tests/integration/test_support_buyer_view_runtime.py -q -rs --tb=short`：3 通过、0 跳过。明确准备/纯指南/错误准备被核对为询问三类，经真实 FastAPI+SDK+PG 隔离 schema 验证：buyer_view 原样持久、CHECK_REQUEST 持久、completed 复用和过期租约恢复一致、fence+1、恢复新增模型/工具调用 0。新模块 hash 与 request-check-v1 入 manifest；旧 completed 结果仍返回，旧在途 manifest 不匹配则拒绝且无新调用。输出 `tmp/request-check-pg-final.log`；自有测试 schema 按 fixture 清理，演示 PG 恢复原停止状态。
- `ruff check` 生产 support 目录及本批测试通过；`mypy` 五个生产修改文件通过；`git diff --check` 通过。中间 Ruff 发现导入顺序和长行，已修；脚本写测试时一度改变换行符，已按各原文件格式恢复，无整文件格式噪声。
- 旧结构脚本首次接线后 69 项失败，补显式正向核对前提/对应次数与 attempt 断言后 29 项失败，随后仅剩 1 个误增的咨询修复调用数断言，修正为实际 3 次后收口。所有最终原门禁断言保留，未通过删除断言或跳过新增失败交付。
- 费用账本最后核对为 3639、无在途 lock。未执行 Java/前端重新构建；本批没有改它们的代码或公开协议。未进行新真实模型生成，也未宣称整轮线上验收通过。

## 已知边界与取舍

原设计将规划器的 goal 直接作为产物准入，本批修复了这条缺失的程序边界。但自然语言目的仍由模型判断：规划和核对都误判时，原文包含检查无法证明客户真实意愿。新增核对不是人工授权、不是“绝不误判”的证明，也不能提供泛化准确率。代码能保证的是未核对、不完整、不同动作或否定/不明确的核对结果不会生成操作产物。

代价是候选操作通常多一次内部模型请求；目标纠正换操作时最多再一次，均计入原预算，首正文延迟与真实判断效果尚待新版本实测。纯 EXPLAIN 不增加核对调用。没有改成所有准备都必须点独立按钮，以保留用户已认可的自然语言准备功能；如需不依赖模型的意愿硬边界，需要另行设计显式准备入口。

下一轮真实复验应保留本轮反例，增加未见过的询问/明确准备/暂缓/多事项表达，在新的有界请求额度内完整运行，分别记录发布与语义结果，不复用原错误前缀假装新验收。旧额度已用完，本批不自动收费复测。
