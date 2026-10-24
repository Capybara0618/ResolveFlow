# 新编排独立对话与确认建单验收

2026-10-24，按docs/customer-agent-orchestration-acceptance-v1.md及用户授权执行。原默认staged-v1，新候选orchestrated-v1及RAG/模型/预算保持。五新合成329元LOST订单，四组6消息和主链1消息，主链最多初始Case调查1run；不审批/退款，不自动重发失败题。

## 准备

新增accept_support_adoption_v1.py、controls/primary两个CJS驱动，复用现有账户/购物/发货/物流场景/会话/原始计量。primary复用原完整网页确认逻辑，独立新目录，旧脚本/失败保持。四组逐组保存状态/内存/来源/草稿/前端事件；机械检查后还有Codex逐条源审，SUCCEEDED不等于语义通过。

实际命令：Python Ruff/py_compile、两CJS node --check通过；prepare已创建policy/correction/pause/human/primary五单与会话，provider_requests0、全局账本2108。准备期间核对票据API以ticket_id读取，脚本import排序已修正；执行前统一冻结最终脚本hash，尚未执行或重写任何真实结果。source_files/15保护文件SHA及固定输入见plan.json。

先精确commit普通push核实，再无在途时显式启用候选、controls仅一次；保存所有请求费用并源审，通过后primary仅一次。所有功能/语义及工程无新增回归后才切日常默认。结果/失败/未运行和下一步集中更新本报告，当前唯一进度仍在tasks/todo.md顶部。

## 四组真实结果：三组通过，独立人工失败

六条消息各一次，21真实请求、准确46629输入/2177输出token、0未知，账本2108→2129。policy3模型、纠正3+3、暂停4+3均发布正确且无修正；人工5模型含一次修正仍INVALID_DECISION。原始controls-runtime.json SHA 1f581b7e39e1c9b6138c3f68e68f300501b569d48b86b2cf601681251987149a，保留冻结。controls-review.json逐条源审通过前三组；截图和browser事件包含真实暂停草稿STALE/不能直接确认。

人工正确接受MERCHANT_REVIEW目标、ORDER/SHIPMENT已取证、程序GUIDE有效；两次RESPOND都把拟转交摘要写在正文，漏独立handoff_reason。实际反馈点名该字段后仍遗漏，失败未发布、无核查单/Case/退款。根因是目标未编译成本轮明确输出合同，通用示例只有parts，原因字段在通用Schema可选；不是RAG检索或事实不齐。

主链按门槛未运行、默认未切换，旧业务/索引/15保护文件保持，无在途。先保存失败普通push核实，再离线实现按已接受goal/生命周期/来源状态生成明确回答合同，统一覆盖退款和人工。禁止正文自动冒充可共享摘要或删除校验来通过。

## 离线修正：按目标编译本轮输出合同

orchestration.response_contract按accepted goal/READY/lifecycle生成精确事项及退款/人工原因字段的完整示例；COMPOSE实际system末尾接该合同，替代只有parts的通用示例。NEEDS_CUSTOMER时按状态省略，暂停/取消/已解决/BLOCKED不索要可办理原因。原Response校验/金额/来源/一次纠错保持，未启用供应商强约束解码，也不把正文当原因兜底。

新增6红测（缺方法/实际请求无完整例子）→控制/SDK合计26过；3源码strict及Ruff通过。真实临时PG/API/流式/store18过0跳过，扩大客服/契约427过/6既有无citation跳过/1既有v2指南诊断失败，无新增回归。实际命令沿原工程验证入口，未跑Java/Web构建（无该侧变更）。

output-contract-diagnostic.json对原人工5模型/3工具做显式离线重放，0网络/业务写；新实际请求有handoff_reason键及实际t1例子，但原漏字段响应仍INVALID_DECISION，原失败未重算成功。

用户授权目标仍为四组与主链完成：成功前三组不重跑；修复后只补1条不同措辞人工确认（新独立运行、原失败保留），通过后执行原定尚未运行主链。本批上限由7客服消息增为8，Case调查仍最多1；不另开矩阵、不刷同句。先固定新确认输入/源码/原失败hash再执行，失败停止依赖链路。

## 有限修正确认准备

f94ede7实现已同步；新verify_support_contract_v1.py及recheck/primary两个CJS脚本Ruff/编译/node语法通过，独立recheck-v1计划冻结当前源码/旧失败/旧计划/脚本hash。继续同一人工失败会话但使用合同中固定的不同措辞新消息；原失败run/输入/源审不改。主链使用已准备但尚未发消息的primary订单，无新建订单，不重跑前三组。全局usage2129、0新增模型；提交普通push核实并无在途重启所属新profile后仅执行新人工一次。

## 有限新人工确认通过，保留脚本观察错误

新人工4请求、0修正、11608输入/435输出、0未知，usage2129→2133，run c0c9ba17-e53a-4188-9d6a-d5f9edcd2230实际SUCCEEDED并返回独立handoff_reason。原浏览器误读上一轮残留失败提示而提早退出，controls-runtime的false保留；通过独立0模型continuation读取已存结果完成摘要编辑/选择共享/商家投影，未重发消息。新[源审](recheck-v1/controls-review.json)明确原失败/新成功/脚本观察错误，前三成功组未重跑。下一步仅原定尚未执行的确认建单主链，完整结果通过前不切默认。
