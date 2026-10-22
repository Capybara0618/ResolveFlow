# 客服中间层职责重构

2026-10-22。按[方案](../../docs/customer-agent-state-refactor-v1.md)完成陈述接口、会话状态、调查需求/关键事实和错误反馈四部分工程接线。**已经证明保存的失败机制有对应处理；尚未用新真实模型实验验证整体质量。** 默认仍为single，可选staged-v1，网页未部署。

| 原问题 | 本批变化 | 实际验证 |
| --- | --- | --- |
| 模型需要生成陈述id/关系数组，误把助手建议当替代目标 | customer_claims只提原句/topic/变化及可选真实target；程序确定id/原句位置/关系。无效可选项不落记忆，有界warnings可见 | 新增、替代、撤回、未知目标、假原文、助手建议、原子状态验证；原memory_updates严格兼容 |
| 回答失败后，合法暂停也无法供下轮使用 | conversation_update与answer独立；Case校验身份/版本/原句/fence后继承已接纳状态，失败仍不发布答复 | 实际PG：暂停接纳→缺来源答复失败→保存→0新调用重建→原id恢复；Java实际MySQL：失败无助手消息但下一轮收到PAUSED |
| 理解阶段遗漏来源需求后无法补充 | REFINE_NEEDS仅对当前焦点追加，最多2次，不删旧需求、不改会话事件、不重置预算 | 缺GUIDE反馈后实际读取才发布；错误id/重复/空/夹带事件拒绝；ORDER追加与金额填充可重建 |
| 自报needs齐全但具体订单金额无权威 | 四种事实占位符由程序从同run/同订单行/有版本的ORDER或SHIPMENT填值、关联引用 | 商品展示999元不影响真实ORDER123.45；PAID与LOST分别来自订单/物流；错源/跨行/未读/缺币种/版本/金额拒绝 |
| 反馈只给笼统错误，失败轮后继续又因前态冲突失败 | OPEN事项RESUME作为幂等继续，已闭合仍须REOPEN；反馈含实际前态/提议/合法选项，Schema枚举含expected | 新4项先全失败后通过；关闭事项不得被RESUME重开、组内非法成员仍原子拒绝 |

唯一循环仍由AgentScope 2.0.8驱动。新理解/需求修订/纠错都进入原模型调用账及预算；持久模型结果重建不新增请求，未完成run的manifest变化仍拒绝。没有增加多Agent、模型路由、RAG算法或业务写权限，没有修改旧冻结清单/评分/模型响应。

## 验证结果与失败

- 最终广集：`test_support*.py`、`test_customer_agent*.py`单元及集成、咨询契约，共299项：**294通过、5失败、0跳过，23.54秒**。5项是旧readiness评测的冻结预检或依赖该预检的测试，均因原context.py与历史清单不一致而拒绝。[测试摘要](verification.json)保留逐项状态。不是全套通过。
- 已逐字节核对：当前context.py与开工基线4ad7611相同，本批没有改它；旧冻结hash64fd301b…、当前7608f04b…，不能修改旧hash迁就新代码。后续真实质量评测必须使用新版本。其余当前功能/新测试均在通过项中。
- Java `SupportApiTest`：20通过、0失败/错误/跳过；实际独立Testcontainers MySQL，未连接演示MySQL。Maven约60秒；定向Spotless通过。覆盖跨行/错误输入版本/伪造客户原句拒绝、旧输入不发布、同会话继承与内部状态不外露。
- 9个改动Python生产模块strict mypy通过，相关Ruff通过。旧冻结失败不归为本批模型质量失败或真实业务成功率。
- 红测：陈述接口11项首10失败/1通过；会话解耦Python首1失败/1通过、Java新2项首全失败；需求修订7项首2失败/5通过；关键事实首9项5失败/4通过；反馈4项首全失败。新能力通过后保留失败及断言，不修改历史Gold。
- 开发中曾出现提示窗口超限、旧任务反馈次序变化、类型检查和导入排序问题，均修正后重验；没有扩大窗口或删任务断言。两个旧OPEN恢复拒绝夹具改为实际闭合状态，继续验证非法重开/批量原子性。一次PG重建出现RUN_BUSY，后续局部及广集未复现，原因未确认，不能称已根治该偶发现象。另有漏根PYTHONPATH的命令及恢复夹具误换mock_script，纠正测试命令/同脚本后通过，门禁未放宽。

实际命令（根目录/agent目录分别执行，日志保存在忽略的tmp/customer-agent-state-refactor-v1，不提交含环境信息的完整Java日志）：

```powershell
# cwd: agent; PYTHONPATH=仓库根; RESOLVEFLOW_AGENT_DB=本地55433测试PG
$tests=@(Get-ChildItem tests/unit/test_support*.py,tests/unit/test_customer_agent*.py,tests/integration/test_support*.py,tests/integration/test_customer_agent*.py | ForEach-Object {$_.FullName})
.venv/Scripts/python.exe -m pytest @tests tests/unit/test_contracts_support_agent.py -q --junitxml=../tmp/customer-agent-state-refactor-v1/python-final.xml
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent src/resolveflow/support/engine.py src/resolveflow/support/protocol.py src/resolveflow/support/memory.py src/resolveflow/support/tasks.py src/resolveflow/support/stages.py src/resolveflow/support/dialogue.py src/resolveflow/support/grounding.py src/resolveflow/support/guidance.py src/resolveflow/support/service.py
# cwd: java; JAVA_HOME=本机JDK21
./mvnw.cmd -pl case-service -am '-Dtest=SupportApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
```

## 能说明什么，尚不能说明什么

这次把客户语义提议和程序状态维护分开，把答复发布与已验证会话变化分开；通过脚本模型、实际SDK/API和数据库验证。不会把本地手工改写的提议算成真实模型正确响应。

关键来源接口只支持PAID_AMOUNT、ORDER_STATUS、SHIPMENT_STATUS、CARRIER_CONCLUSION。常见数字CNY/元/￥/¥金额须与该part引用的ORDER整行实付一致；这是当前整行退款范围的有限检查，不适合差额/部分金额/政策费用解释。中文大写金额、任意自由文本状态或语义关系没有全面验证，不宣称消除所有幻觉。一般政策解释可以不读取订单。

新customer_claims中的有效提议逐项接纳，无效项有警告且不产生错误记忆；模型完全漏提或语义标错仍可能影响后续体验，旧memory_updates仍需严格合法。不会因为“没阻断回答”而把记忆记录算作正确。

理解阶段已独立接纳后，答复失败可保存状态；若理解本身未被接纳，不能把它当成功变化。未完成进程仍需原受fence保护的调用重建，不能仅靠SDK会话保存。重构没有增加退款或人工共享权限。

下一步适合固定新版本、保留原失败样本并增加不同表述，做有限真实对话源审，观察协议错误是否减少、完整对话是否成立及调用/耗时。当前未执行该批，不能使用旧结果补算新成功率或更新简历数字。

## 数据与提交

独立小步已正常推送：a122a87（陈述）、0da003d（状态）、a44d187（需求修订）、5d75185（来源）、e1a9532（反馈）。[收口记录](completion.json)包含最终代码及证据hash。

真实模型请求0，ledger1868保持；public11表全行hash、四历史脏文件、旧v2/v3及两候选真实raw保持。自有测试schema已清理，PG已stop/原卷保留，项目端口关闭。原有图片/日志及无关工作区改动保留。
