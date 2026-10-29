# 展示链两项修复（2026-10-29）

状态：两项修复及针对性真实复验通过。最终受控调查5/5、正式咨询接口2/2及实际买家页面通过；保留中途失败。不是全量模型质量或一次新退款闭环的结论。

用户授权修复上轮剩余的政策引用与模拟到账措辞，并继承针对本轮真实模型不另设次数上限的授权。原27请求报告、错答/失败、成功退款及旧run/manifest保留，不重算历史或重复付款退款。原4历史脏文件不动。

首步：调查PolicySearchBridge复用PolicyIndex.small_context，同商家/manifest/冻结generation内规则<=8且序列化<=8192 UTF-8 bytes时完整读取，明确COMPLETE_SMALL_SET；大集仍原dense/top_k，不自动启用融合或rerank。P2保留政策标题和完整原文，指导区别丢失/损坏/普通在途/签收，未命中不借无关条款支持结论。身份、预算、本地读取与引用hash门禁沿用。不是规则命中即适用，也不宣称有通用语义裁判。

新增真实PG隔离schema+实际AgentScope脚本模型检查先因缺retrieval_context失败。小集可完整读不再需要encoder，原encoder错配测试移到真实9条大集保持原拒绝检查；新增大集dense/top1边界，原字节保持。当前64项（政策执行/大小边界/冻结generation/主体hash、context及引用验证）通过，Ruff定向修正测试既有导入顺序后再检查。无provider请求或业务数据写入，测试schema按原fixture清理；本地原日志tmp/display-chain-fixes-20261029。


第二步：只读退款结果part采用presentation=REFUND_RESULT，模型选择该用途但不提供text/guidance。程序从本run ORDER.refund_application按当前Java状态生成结果、已退金额、必要下一步及模拟资金说明，金额仍用原grounding校验；普通问题保留模型text，同轮可分别回答，不按关键词覆盖整条消息。不允许准备/暂停事项借结果模式产生申请动作。NONE必须显式权威否定，来源缺失/失败拒绝结果模式；批准/执行中/UNKNOWN不当成功，成功缺金额不从实付填补。编译后仍原buyer-view-v1/AnswerParts/Java协议，内部presentation不进入业务写入口，service manifest纳入refund_result.py内容哈希，旧run不迁移。

13项新结果测试先9失败2已有拒绝边界通过，随后补独立商品问题及准备/暂停边界共13通过；初版准备边界夹具未核对请求，先在evidence not ready处停止，补原approve_requests后走到真实模式门禁，记录该夹具错误不弱化校验。客服590项全量通过、Ruff通过（新导入顺序与行宽已定向修正）。未改前端布局、Java、政策源/索引或原成功退款，接下来保留数据部署并对当前完成订单真实追问，调查取证另用真实模型+明确合成/保存事实的受控场景检查语义，不把合成事实试验冒充新业务退款。

## 真实复验与补修

真实服务：保留原数据库、三份政策源及原READY generation，`start.ps1 -SkipBuild -NoBrowser`恢复三Java、AgentScope实际生产循环、DeepSeek `deepseek-flash`与5174网页。两个正式咨询run沿原完成订单，不创建申请或新退款。调查试验为**真实provider + 生产AgentScopeRunner/ProposalVerifier/PolicyIndex + 保存与合成的只读业务事实**，不调用实际Java工具，不写业务run/回调；不是strict replay，也不是五笔新交易。

第一轮受控驱动因严格DTO要求从JSON转换枚举而全部TOOL_FAILED，各已花1次请求，共5次，证据保留。修正驱动并在provider调用前验证所有fixture后，第二轮4/5技术完成；已核验丢件虽然已选中R-LOST-001，仍把订单LOST和人工核验当承运来源，未读get_shipment_trace，被原INVESTIGATION_FACTS_REQUIRED门禁拦截。失败run `2c8fe202-4c7d-4fa7-a7ad-19c3ef7dc14f`保留，不把拒绝安全地发生当作调查通过。

根因确认：原拒绝反馈重复列出所有条件，没有指出本次具体缺口。追加的小修仅从已有paid/confirmed/lost/delivered/occupied/冲突布尔检查生成失败项，区分承运来源未读取、已读取未引用、已引用但未确立；已经满足的核验不再报作缺失。不改变判定、权限、修复次数、工具路径或金额条件。3项反馈检查先2失败/26通过，修改后调查来源、verifier、纠错、终止与循环共90通过，真实PG纠错恢复7通过，Ruff通过。一次错误的测试文件名未运行检查，随后用实际存在入口执行，未记作成功。

最终一轮固定五场景一次复验，5/5完成，实际请求与引用逐项源审：

| 场景 | 结果 | 实际引用 | 审查结论 |
| --- | --- | --- | --- |
| LOST、无签收、未人工核验 | MANUAL_REVIEW | R-LOST-001、R-MONEY-001 | 明确缺关联CONFIRMED，商家核验；未套用DMG |
| LOST、无签收、关联核验CONFIRMED | REFUND建议329元 | R-LOST-001、R-MONEY-001 | 初次漏承运来源被反馈后补读并引用，保留审批边界 |
| 已送达、损坏核验CONFIRMED | REFUND建议329元 | R-DMG-001、R-MONEY-001 | 仅用于损坏，未扩成丢件 |
| 普通IN_TRANSIT、无丢失结论 | MANUAL_REVIEW | R-INTRANSIT-001、R-MONEY-001 | 未把运输两天当退款资格，未自动拒绝整个申请 |
| 显示签收、客户称未收到、未核验 | MANUAL_REVIEW | R-SIGNED-001、R-MONEY-001 | 保留签收争议，要求商家核实 |

每例政策读取均为6条COMPLETE_SMALL_SET，原规则原文/hash、manifest及冻结generation保持。最终丢件run `1d63f889-6a89-4e68-80d4-b154ddd9fbca`补读成功，是反馈帮助模型补齐来源的证据；不是解除来源门禁。

## 买家正式答复与页面

正式咨询run `09d22653-9b03-42a8-bb3a-bf4f2d8180b3`，4次真实请求，SUCCEEDED。模型首次同时填presentation与text被原新协议拒绝，一次修复后只选择REFUND_RESULT，程序据当前ORDER退款投影生成：

> 这笔模拟退款已完成，金额329.00元，你不需要再操作。本次不涉及真实资金到账。

第二个混合问题“退款现在是完成了吗？这副耳机是什么颜色的？”run `324b6d72-e79b-4735-8ba6-01a816f3edcb`，4次真实请求，SUCCEEDED；第一part为同一事实生成结果，第二part正常回答“这副无线降噪耳机是黑色的。”，没有因结果模板丢掉独立商品问题。两次都从当前Java CLOSED_SUCCESS/version9、32900分生成，无到账承诺。

浏览器恢复后实际buyer09登录正式5174页面，核对两条新答复、混合问题与退款回执一致，截图本机`tmp/display-chain-fixes-20261029/buyer-final-live.png`（1016×884）。保留原错误历史消息；截图仅证明实际页面已显示新答复，不宣称重做全站视觉验收。

## 数量、资金与验证边界

本批共**63次真实DeepSeek请求**：驱动失败5、第二轮调查24、最终调查26、正式咨询8；所有失败与修复计入，provider非估算input **152139**、output **7680** tokens。与上轮27次报告分开，不混记。详情见[脱敏汇总](display-chain-fixes-20261029.json)，原始输入、输出、失败、usage与manifest仅保存在本机忽略目录。

结束时只读核对：9工单、6退款操作、26订单/行保持；原操作`c3dbfd77-0d9c-4ec4-b6e9-e62c8636cff9`仍SUCCEEDED/32900分/version3、provider请求总数仍1，原订单已退32900/预留0；没有新退款或重复提交。两端活动run均0后仅重启所属agent-live加载最终校验反馈，其他服务与数据保留。

实际离线入口均为`agent/.venv/Scripts/python.exe -m pytest`：

- 政策：`agent/tests/integration/test_policy_search_action.py agent/tests/integration/test_support_small_policy.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_batch2.py agent/tests/unit/test_context_citation_survival.py agent/tests/unit/test_proposal_verifier.py -q`，64通过。
- 客服：本批`test_support*`单元集合590通过（含新增13项），原Starlette弃用warning保留；`test_support_stream_runtime.py test_support_conversation_update.py`集成7通过。
- 最终来源反馈：`agent/tests/unit/test_investigation_sources.py agent/tests/unit/test_proposal_verifier.py agent/tests/unit/test_correction_loop.py agent/tests/unit/test_investigation_loop.py agent/tests/unit/test_investigation_termination.py -q`，90通过；`agent/tests/integration/test_correction_recovery.py -q`，7通过。
- PG集成环境`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`，沿原隔离schema fixture，不清业务库；改动Python文件Ruff通过。

初始系统python版本不匹配、恢复前连接拒绝、取证SQL误写不存在call_id列均为验证驱动错误，纠正后执行；未算业务/模型成功。未重新跑Java/前端全量或新付款退款：本批未改它们，原真实闭环证据沿上轮报告。完整小集仅保证规则可见，通用政策语义正确仍需模型与商家核验；当前5例不代表所有问法和状态永远正确。
