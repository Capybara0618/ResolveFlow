# 建议、补证责任与停止来源改进

2026-10-06，接续[保存真实请求的来源审查](../agent-rag-source-review/README.md)，按[本批规格](../../docs/agent-decision-handoff.md)实施。**已修复可确定的反馈、补证协议和停止归因问题；生产检索仍是dense，未新增模型调用，不将工程通过宣称为真实模型质量提升。**当前进度仅tasks/todo.md顶部。

## 行为变化

|触发|原行为|本次行为|
|---|---|---|
|finding引用没有放进evidence_refs|只有根级Schema错误，易被归为格式问题|SOURCE反馈定位review_findings.i.observation_ids，指出缺失的O编号；模型自行正确引用或删掉不支持的finding|
|CONFLICT只有一个来源或重复来源|泛化格式修正提示|点名不同来源数量约束，明确不得为了数量加无关来源；仍只有一次修正|
|客户问题field是履约、支付、资金槽、承运结论或核验结论|部分系统字段可被要求由客户提供|拒绝明确的系统字段，提示工具/商家核查；包装照片、损坏说明、客户收货陈述仍可问|
|REQUEST_INFO没有具体补证事项/有空白项|可能形成空泛补证建议|动作门禁及最终方案校验都要求非空missing_evidence；有效建议仍PROPOSAL，真正客户提问仍ASK_CUSTOMER→QUESTION|
|已读来源报告占用或业务读取失败|事实已保留，但摘要可能漏掉关键阻碍|既有P1指导提示短编号及当前阻碍、责任与下一步，P2原字段/hash/版本保留，不替模型决定退款|
|模型动作被拒绝、SDK需结束循环|占位ESCALATE被轨迹记为DECIDED|内部回复标HARNESS，轨迹为STOP/REFUSED/真实reason，最终decision仍空；有效模型终局标MODEL|
|有效模型主动ESCALATE|FAILED回调可能把COMPLETED作为转交原因|使用模型reason_codes，空码用NEEDS_HUMAN_VERIFICATION；Harness失败仍报告其真实错误码|
|最终校验读取missing_evidence字符串列表|错误复用对象列表助手，字符串被全部过滤掉|经Schema校验后直接保留原字符串列表；有效补证不再被误拒，既有退款/拒绝缺证限制继续执行|

这些机制按字段、引用关系和读取来源工作，未引用Axx案例ID、客户固定问法或Gold作为生产路由。并非自然语言责任/幻觉的全能判定器：系统字段拦截只覆盖列明结构字段，任意prompt或missing_evidence中的隐含责任仍需语义评测。CONFLICT来源数满足也不证明冲突语义成立，不自动生成事实或补引。

## 输入与持久边界

- 系统提示仍343字符；新增的是责任/转交说明，不再堆整份材料。P1阻碍仅针对实际已读当前来源的RESERVED/UNKNOWN/CONSUMED或读取错误，无阻碍不生成该段；同来源取最后读取，旧成功不遮蔽新失败。实际下一轮模型输入已验证包含O编号/占用提示，原金额及Observation保持。
- 失败提示是解释指令，不是可引用事实；正文、政策条件/例外和短引用账本不改。模型仍决定调查顺序，不固定全工具链，不增加query改写LLM、RRF或重排。
- `ModelReply.origin/control_reason`仅内部适配元数据，不开放为模型动作字段。原provider响应、usage、durability保存边界保持。修正耗尽不伪造有效ESCALATE，也不多发一次模型请求。
- context变为p0-p4-v13-decision-handoff，verifier为python-citations-v7-decision-handoff；prompt/tool schema/source也进入manifest。原run或v13回放不得悄悄换新逻辑，明确不兼容。新[回放清单](../../evals/replay/decision-handoff-v14/manifest.json)冻结28输入与36包文件；原14行为加4类通用变体，总18包。
- FAILED回调协议不含summary。本批修正其原因码和运行轨迹，**模型的完整转交摘要尚未接到商家失败时间线**；未改Java/前端协议，不声称商家已看到全文。补证建议也不会自动发给买家。
- 未重启常驻调查、消费队列、修改业务记录/政策索引或退款授权；下次正常启动后新调查加载源码，旧manifest不能静默升级。原来源报告/标签/Gold/旧回放共66项与HEAD逐字节核对不变。旧21输入审查在原5597f5c版本复算，新源码不能靠改旧manifest hash冒充原审查。

## 验证

|检查|实际结果|证据|
|---|---|---|
|20文件相关单元回归|307 passed /0 failed/errors/skipped，11.13s|[最终JUnit](unit-v2.xml)|
|11文件隔离PG/MCP/恢复/回调/导出/回放|111 passed /0 failed/errors/skipped，84.55s|[集成JUnit](integration.xml)|
|当前默认评测入口strict|18/18 MATCH，原包不覆盖|[strict报告](strict-v14.json)|
|相关Ruff、差异、输入hash、历史字节、链接/公开文件检查|通过|[收口核查](verification.json)|

418项是两个不重叠测试集；strict入口另报18包，不将其重复相加成为新的独立样本。新增31条单元用例、2条完整数门禁、2条恢复用例、4条导出+4条已冻结回放变体及1条旧版本不兼容检查，共44项。所有模型为脚本mock；真实的是PG、MCP传输、SDK和持久边界，不是本轮真实LLM质量。

新恢复用例在第二次模型响应已保存后注入崩溃，恢复复用两份记录，仅新发第三次mock响应，工具只执行一次；有修正能形成FACT建议，无修正保留FINDING_SOURCE_INVALID及HARNESS停止，不获得第二次修正。strict依旧禁止网络/原业务库、缺工具或篡改请求明确失败；本批未重建Docker隔离镜像。

开发失败如实保留：最初23条失败注入19 failed/4 passed，随后23通过；第一次集中命令使用不存在的test_harness_actions.py，未运行测试，改用实际入口后181通过。Lint长行/导入修复后通过。首次PG导出1 failed/23 passed/18 deselected：正确补证仍在最终校验误被过滤；新增wire负测复现（1 failed），修复列表提取后53 passed/18 deselected，重新导出新tmp/replay-dev2并冻结。第一次305项JUnit保留为[中间记录](unit.xml)，加入实际输入/最终回调边界两项后新报告307通过，不覆盖旧结果。初次tmp候选包保留不作为最终回放。

未运行全仓、mypy、Java、网页或新付费Agent对照；旧16类型诊断与8可见历史失败不因本批418项消失。不承诺任意自然语言幻觉检测、图片真实性或真实客户泛化。历史四个脏文件及旧图片/日志不提交。

## 实际入口

```powershell
$env:PYTHONIOENCODING='utf-8'
# 单元（20文件清单，复跑结果用新路径）：
$checks = Get-Content reports/decision-handoff/verification.json -Raw | ConvertFrom-Json
& agent/.venv/Scripts/python.exe -m pytest -q @($checks.unit_files) --junitxml=tmp/decision-handoff/unit-repeat.xml
# 集成以本地PG55433连接串设置RESOLVEFLOW_AGENT_DB，自动仅用临时隔离schema：
& agent/.venv/Scripts/python.exe -m pytest -q @($checks.integration_files) --junitxml=tmp/decision-handoff/integration-repeat.xml
# 可直接运行的无收费默认strict入口；结果路径必须新建：
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --output tmp/decision-handoff/strict-repeat.json
```

本机导出设置RESOLVEFLOW_REPLAY_GOLDEN_DIR/RESOLVEFLOW_SHORT_REF_GOLDEN_DIR为tmp/decision-handoff/replay-dev2，运行新unit及三个集成文件`-k 'not committed'`（此阶段仅生成新包，不把筛选当最终验收）。随后18个pack.json/files.json逐个read_pack+strict复核、复制到全新v14路径并冻结；最终111项没有筛选或跳过。清单包含真实source身份及逐文件SHA，缺包不能报0步骤通过。

后续优先固定版本做整体真实Agent对照，观察来源反馈是否真被模型采纳、系统/客户责任及摘要是否清楚；沿用原输入和Gold，增补通用变体，保存新结果，不默认重复收费全套。若要在网页展示转交摘要，需单独补Python→Java→网页的可选说明协议及验证，不能仅把字段塞进现有FAILED回调。
