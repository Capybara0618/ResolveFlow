# 五场景真实展示链联调（2026-10-29）

状态：单订单五场景的真实模型/模拟交易闭环已跑通，完成后追问的状态矛盾已修复并真实复验。保留首轮政策引用与末句措辞两项质量问题，不宣称模型所有场景全绿。

用户授权真实模型和实际操作验证，不设本轮请求次数上限。范围为一条本地演示订单的五场景闭环，不开展额外批量评测；保留生产Harness的单run权限、预算和终止规则。真实模型与本地模拟资金/物流分别标识，不以合成截图替代本次运行，不清库或重做基础数据。

验收口径：商品/规格/金额一致；实际模型按订单事实通俗答复，实际等待及流式回复可结束；退款摘要由买家核对并显式确认；商家按当前权限核验/审批；真实本地退款操作成功后聊天、申请和订单状态/金额一致。理解、事实、权限和能否操作为阻塞项，轻微措辞与审美偏好为非阻塞建议。已有异常边界由原自动化检查覆盖，本轮不为文案清零重复收费。

启动前只读检查：原8工单为5 CLOSED_SUCCESS、3 PENDING_REVIEW；36咨询run为29 SUCCEEDED、7 FAILED，无待处理咨询；原9调查绑定全部DISPATCHED，PG调查8 COMPLETED/1 FAILED，无QUEUED；5退款操作全部SUCCEEDED；两端事件Outbox共10条PUBLISHED，18回调DELIVERED。没有遗留待自动推进的旧任务。沿原MySQL/PostgreSQL/Redis/RocketMQ卷启动，不执行reset。

准备与最终结果、实际模型请求/usage、订单/申请/退款身份及失败会在本文件后续追加。原始响应、截图与运行日志仅本机tmp/display-chain-live-20261029保存，提交记录不含访问令牌或密钥。

## 已执行与阻塞

buyer09通过正式网页新买无线降噪耳机黑色一件，实付32900分。订单`bb1eb1cf-4720-428c-8179-6ef93ce6fe70`、订单行`SHOP-6ec5216c-61b5-431a-8a9f-e87dc05d1f2d`；商家网页模拟发货后，仅对本行用物流模拟器追加LOST事件，原数据和政策版本保持。

两轮真实咨询分别查询物流、准备退款草稿；买家确认前本行0工单，编辑原因并显式确认后创建`80ac23d2-2fbd-4b4c-88ec-a6a1e41a9534`。首轮调查`e7d27170-126f-5229-a6f9-42744ec65a4b`转人工；商家核验材料后revision2调查`9e620607-c345-5855-b034-cb8bd8eb2876`引用R-LOST-001提出REFUND，商家网页独立批准。同一退款操作`c3dbfd77-0d9c-4ec4-b6e9-e62c8636cff9`成功32900分，模拟provider记录1次请求；Java账本已退32900、预留0。聊天卡、独立详情和订单均可查看完成结果。原8工单、5退款及36咨询的基线所采字段逐条保持，不等于全库所有字段快照比较。

发现并修复：CustomerCaseService先判断授权已消费，再判断终态，导致完成仍返回“进入执行阶段”。改为终态优先，只修正公开说明，allowed_actions和金额保持。CustomerWorkspaceApiTest新增完成状态及已消费失败状态对照，先1项失败，再全类9项通过；当前2文件定向Spotless与package通过，Case重启后实际回执已显示“申请已结束，仅可查看记录”，16px正文、1280×720无横向溢出。截图`tmp/display-chain-live-20261029/13-live-refund-receipt-fixed.png`。

真实质量失败保留：首调查检索query“包裹丢失 物流未送达 退款 商家审批 条件”返回INTRANSIT/DMG/UNSHIPPED，遗漏LOST；模型扩大解释DMG为也支持丢失。该轮MANUAL_REVIEW不产生退款授权，不能把引用身份校验VALIDATED当语义正确。第二轮query变化后返回LOST并正确引用，但不抹去首轮质量失败；本轮未改政策、索引或固定问法来追单题满分。

曾发现阻塞：退款完成后问“现在这笔退款办好了吗？退了多少钱，还需要我做什么？”，run `0a70b285-aaed-4086-ab8f-e072eadb8bcd`回答“还没有办好，目前没有已提交或已退款的记录”，与真实CLOSED_SUCCESS相反。实际工具order仅有原付款商品信息，shipment/policy没有退款执行事实；conversation_state.has_ticket指独立咨询核查单，并非退款申请。后续以只读事实接线和表达合同修复，原错答保留，不重写历史。

事实接线子步：SupportAgentTurns复用CustomerCaseRepository.related与CustomerCaseService.read，沿绑定商家/买家/订单行只返回公开refund_application白名单，来源版本组合订单版本与申请id/version；不传调查、授权身份或材料。Java两项新增接口检查先失败；实现后2项及原fence检查通过，去掉一项错误的消息数量夹具假设后，完整SupportRefundApiTest及fence共49项通过。覆盖无申请、同line但他人/他店申请隔离、当前状态变化、金额缺失不捏造及来源版本变化。OpenAPI说明、Java边界说明和合成fixture同步。Python渲染/来源校验和部署后的真实复验仍在后续子步；此处不把接口绿灯等同模型已修好。

Python子步：沿既有ORDER需要/来源与AnswerFact渲染，新增REFUND_STATUS、REFUNDED_AMOUNT；后者严格要求当前行CLOSED_SUCCESS和Java整数分金额，不从原实付/商品展示/批准金额填补。NONE须显式权威否定，缺字段/读取失败保持未知；指导模型查询退款须读ORDER，has_ticket不是退款状态，完成后不沿用申请前条件。原语义理解、唯一AgentScope循环、确认门禁及流式占位符隔离保持。新13项先3失败10边界通过，修复后54相关、全客服577通过，fixture接入后13再次通过；Ruff通过。新测试最初用了无效intent=ORDER，改为真实OTHER/needs=ORDER后保留有效红灯记录；新增fixture后import排序/未用导入已定向修正。没有用新脚本回答替代真实复验，也没有重算旧run或更换原manifest。

截至前两咨询+两调查共17次真实DeepSeek请求，provider报告input42174/output1662 tokens、非估算；第三次追问另计，最终汇总后追加。真实模型、模拟资金及合成物流明确区分。

实际失败命令：初次Maven参数未整体引用导致生命周期解析失败；全模块Spotless发现ReviewerRunInput、ReviewerRunInputTest、OrderApiTest既有格式问题，未顺手修改；定向参数先误用glob后改正则；首次package因Windows运行JAR锁失败，仅停止所属Case后重建成功。Case启动中一次刷新返回500，健康后恢复。原始失败日志保留，不算业务或模型成功。

## 集中复验结论

| 场景 | 实际结果 |
| --- | --- |
| 商品首页 | 正式商品选择、付款与后续同一耳机/黑色/1件/329元一致；非静态预期图 |
| 买家咨询与退款确认 | 真实查询/准备两轮；草稿可编辑，显式确认才建单，无擅自审批或退款 |
| 商家核验与审批 | 首轮待核验；材料确认后新revision调查，正确LOST条款建议，当前商家独立批准 |
| 调查等待与进度 | 真实调用/事件有始有终；新页面复验由RUNNING自动收敛到已发布回答；不显示虚构百分比 |
| 退款完成与结果 | Case CLOSED_SUCCESS、同一操作SUCCEEDED32900分、provider一次请求、ledger已退32900/预留0；买家聊天/详情/订单一致 |

事实接线后第一次真实复验run `1bb4c0d9-546c-4123-9f6a-f3eb7e320ca9`，4次模型请求，已读取正确CLOSED_SUCCESS/32900且候选答复承认完成；但理解阶段多声明POLICY，最终只引用ORDER，按原政策引用门禁拒绝，FAILED/INVALID_DECISION，未发布候选。这次安全停止不是正确答复，不删校验换绿灯。随后仅明确每轮needs按当前问题重定：办理结果/已退金额用ORDER，页面步骤用GUIDE，资格/规则才用POLICY，不继承旧准备事项取证清单；30针对检查/Ruff通过。

最终按完全相同问法、同一原会话真实复验run `d51a332f-650c-4309-ba12-431539c06750`，3次模型请求，选择ORDER/GUIDE，读取当前refund_application后正确回复模拟退款完成/329元/无需其他操作，未生成新草稿或动作。页面自动由RUNNING更新为回答，聊天回执保持329元完成，截图`16-live-reply-and-receipt.png`。实际1016×884，文档宽1016，输入框底832<884；独立回执1280×720、文档宽1265、正文16px。原错误回复、技术失败与新正确回复同时留存，不能用后者覆盖前者的质量记录。

期间旧页面经历后端热重启后曾停在“处理中”，手动读取能看到FAILED，重载新页面的SSE自动完成正常；只读HTTP也确认正式Vite代理返回200/text/event-stream及合法snapshot字段，未确定旧连接停滞的底层原因。修正前端只在断线时兜底的缺口：所有活动run每8秒只读核对一次，终态停止；无消息重发或新模型调用。新增连接在线但静默的检查先失败，修复后前端39文件299项及build通过，不把此离线故障模拟写成再次真实断网实验。

最终本轮共5次咨询运行（4技术成功、1失败）和2次调查，真实模型请求27次=咨询17+调查10；provider报告input90817/output2459 tokens，全部非估算。含错误答复和失败复验，不只统计最终绿灯。模型为DeepSeek deepseek-flash，唯一AgentScope循环；资金/物流仍本地模拟。两端Outbox各6条全部PUBLISHED，22调查回调DELIVERED。新增1订单/1行/1Case/1成功退款，旧8Case、5退款、36咨询基线所采字段逐条保持。机器记录见[公开核对结果](display-chain-live-20261029.json)，原始快照SHA/调用与截图留本机tmp同名目录。

剩余质量项：首轮人工建议的条款适用解释不正确，尚未修复检索/调查质量；最终答复末尾“后续可以留意退款到账情况”不够贴合模拟场景，但正文已明确模拟完成，回执持续标注不涉及真实资金，没有编造到账日期。按本轮口径，当前操作、金额、权限和主状态可演示通过；不据此宣称所有表达/政策质量已通过，也未扩大固定评测、全项目换肤或并发/UNKNOWN故障实验。原工程说明/Commerce退款测试/verify四文件未夹带。

实际验证命令：`mvnw -f java/pom.xml -pl case-service -am -Dtest=CustomerWorkspaceApiTest -Dsurefire.failIfNoSpecifiedTests=false test`（9过）；`-Dtest=SupportRefundApiTest,SupportApiTest#consultationCredentialCannotReadOtherRunAndOldFenceCannotReadCurrentFacts`（49过）；当前文件正则限定Spotless及package过。`python -m pytest`客服unit文件577过，最终prompt后针对30过/Ruff过；`pnpm --dir web test`299过、`pnpm --dir web build`过。未重跑无关Java全项目、整套并发/未知退款或新批量模型质量评测。
