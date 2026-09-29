# 当前改进进度

## 当前快照（2026-09-29）

- 用户主导后续改进；旧 CXX 序列停止，C12 已取消。当前依据 [审查员优化方案](../docs/reviewer-optimization.md)。
- 已删除 C12 专属未提交样本、评分器、计划、费用脚本、探针/故障/性能脚本。共用检索入口、资金边界测试和数据库/费用记录保留；不清库、不删卷、不重写历史。
- 已完成第一批：审核动作与政策原文接口、无授权人工接管、人工方案、核验后引导、各状态列表/搜索、执行结果与人工决定展示。记录见 [交付报告](../reports/reviewer-workspace.md)。
- 第二批：Agent来源陈述/判断/冲突分项贯通模型决策、回调、Java契约和页面；缺失原始工具正文如实提示。见 [调查依据记录](../reports/reviewer-findings.md)。Python185项、前端31项及构建通过，Java共享契约/回调/复核通过。未调用收费模型。
- 已补齐旧接口的已消费输入保护：工单退回待审也不允许新材料、核验、人工方案和取消。Java相关51项通过，新增4项回归先失败后通过；见[边界修复记录](../reports/reviewer-consumed-input.md)。
- 已完成当前修订调查原始记录投影、引用全匹配、mock标签和缺记录说明，见[原始记录交付](../reports/reviewer-sources/README.md)。Java21项、Python控制面与新增投影、87项OpenAPI、前端34项及build通过；Docker/Gateway/浏览器只读联调通过。未新增退款、未调用收费模型。
- 已完成[计划](plan.md)第一批“核验、补证后的调查闭环”：材料变化会排队新修订并建立新run binding；新run拥有独立deadline并携带已有证据；两条补证路径统一question_id、两轮、等待态和超时约束；页面标识旧版失效与真实下一步。Java 83项、OpenAPI 87项、前端35项及build通过，见[闭环报告](../reports/reviewer-reinvestigation.md)。下一批从稳定mock演示样本开始。
- 2026-09-29用户决定将剩余四批交给DSH/DeepSeek执行；已编制[总约束与四批详细手册](dsh-reviewer/README.md)，保存用户参考图，更新[handoff](handoff-current.md)与计划入口。本次仅文档交接，剩余四批尚未实施；5个已知契约失败列为第二批前置修复。实际通过Python脚本核查11份文档的70个本地链接、所列Python测试路径与Maven测试类；`Get-FileHash`确认参考图与原附件一致，`git diff --check`通过；未重复运行业务测试。
- 集中验证：Java 47 passed，前端30 passed，构建、OpenAPI/fixture与差异检查通过；未调用收费模型。C12专属报告也已删除，空目录可忽略。
- 第二批（DSH执行，2026-09-29）已实施：先修掉5个已知契约失败（Case 18→21、Agent 5→6条路由补入[核心路由表](../docs/core-contracts.md)，四条operation补authority指向，队列表按真实`view`/`query`参数更新并补服务端非法参数用例）；再建立项目名`resolveflow-review-demo`的隔离演示环境（[compose](../infra/compose.reviewer-demo.yaml)、[驱动](../scripts/reviewer_demo.py)、独立MySQL/PG/broker/端口/卷，[样本manifest](../reports/reviewer-demo/samples.json)），七个合成样本（六个展示 + 一个UNKNOWN恢复一次性样本）已实际跑通：AgentScope mock→MCP→真实检索→持久记录→Java复核→人工审批→demo broker→provider→结果回传，UNKNOWN保持原operation与占用。见[交付说明](../reports/reviewer-demo/README.md)。实测178+16项前端契约/驱动单测、25项集成、全量Python 1175 passed；顺带修掉`agent/tests/integration`里5个模块硬编码的过期deadline（含5个原失败的`test_golden_trajectory`）。已知未修：5个`test_committed_golden_pack`在HEAD上就已过期失败（pack记录旧代码版本的prompt/tool hash与已过期deadline），属第四批轨迹回放范围。未调用收费模型。
- 既有前端成果见 [V3报告](../reports/frontend-v3/README.md)；旧任务进度从 Git 历史查看，不作为实施指令。
