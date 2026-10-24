# 新编排独立对话与确认建单验收

当前结论：本批基础功能收口，日常启动已采用orchestrated-v1。独立政策/纠正/暂停通过；人工首轮失败保留，目标输出合同修正后新消息与零模型UI续验通过；聊天自动退款原因→编辑确认→同键同Case→商家未核验材料通过。8客服轮与1Case调查共35真实请求，含所有失败，账本2108→2143，准确81579输入/3697输出、0未知。单例问答6.619秒、确认105ms，不作为p95或跨版本总体成功率。

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

## 原定主链通过与本批合计

[主链](recheck-v1/primary/README.md)一次客服5模型0修正+初始Case调查5模型，10请求23342输入/1085输出、0未知，usage2133→2143。自动原因→编辑保存→刷新→确认→同键同Case→会话进度→商家未核验材料/VALIDATED MANUAL_REVIEW全通过，Case fabd03ac-f159-4b93-8fa6-178f461bf938。未审批/退款，32900/0/0，旧业务/索引/保护项保持。

本批总8客服轮（含原人工失败及一条不同措辞确认）+1Case调查、35真实请求81579输入/3697输出、0未知，usage2108→2143。原21请求失败批/后4请求人工成功与UI观察错误/本次10请求均完整保留；不将不同版本汇总成总体成功率或p95。

有效主链问答首DOM5.244秒、完整6.619秒、确认105ms，主要可见等待是理解/串行工具选择及生成；没有实测依据把RAG当主要瓶颈。功能/源审及工程无新增回归满足本批采用门槛，接下来同步正式启动/状态检查为orchestrated-v1，并进行不发模型的最终审计。

## 默认采用与运行入口验证

正式project_runtime以一个SUPPORT_ARCHITECTURE常量同步start/启动后检查/status为orchestrated-v1；README/local-runtime更新当前入口。原兼容profile仍保留，不改历史评测。旧启动预期有意更新为已批准新默认，并新增“HTTP可用但旧profile不能算完整就绪”两边界测试，4红→runtime/API/驱动46过；Ruff/py_compile通过。

无在途后实际执行status.ps1和start.ps1 -SkipBuild -NoBrowser：复用所属当前新profile/原Java/Web，依赖、3 Java、Python、网页、基础政策精确索引全部健康；没有新增模型请求。接下来只读审计旧业务/索引/失败hash与新Case资金状态，不再追加付费或重跑已通过案例。

## 最终审计与停止写入

819f293默认切换已普通push核实。final-audit.json确认当前HTTP与日常入口均orchestrated-v1，旧业务/政策索引/21保护项与主链持久答案保持；本批恰8客服轮/1Case调查/35模型调用，原人工FAILED仍保留。新Case仍PENDING_REVIEW revision1/version3，支付32900分/已退0/预留0，无授权/退款操作或在途；最终审计与启动未增加调用，usage2143。

实际工程命令（均已执行）：
```
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_orchestration.py agent/tests/unit/test_support_orchestrated_engine.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit -q -k "support or customer_agent_publication or customer_answer or refund_summary" --tb=short
agent/.venv/Scripts/python.exe -m mypy --strict agent/src/resolveflow/support/orchestration.py agent/src/resolveflow/support/engine.py agent/src/resolveflow/support/orchestration_prompts.py
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_support_orchestrated_runtime.py agent/tests/integration/test_support_staged_api.py agent/tests/integration/test_support_stream_runtime.py agent/tests/integration/test_support_store.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_project_runtime.py agent/tests/unit/test_reviewer_demo_driver.py agent/tests/unit/test_support_api.py -q --tb=short
.\status.ps1
.\start.ps1 -SkipBuild -NoBrowser
```

结果：控制/SDK26过，临时PG/API/SSE/store18过0跳过，默认启动/API/驱动46过；扩大客服/契约427过、6既有无citation跳过、1既有冻结v2指南诊断失败。strict3源码与相关Ruff/编译/node语法过；未跑Java/Web重新构建（无业务侧改动），未跑完整仓库或收费性能矩阵，不把既有失败写成全绿。

本批结束后不继续加功能/追单题，旧四历史脏文件与旧未跟踪资产保持。后续可在用户新指示下固定当前版本进行简历量化和独立性能样本；建议先测再决定是否减少模型轮次。当前只完成本合同范围，不声称覆盖所有客服场景或达到公司级生产标准。
