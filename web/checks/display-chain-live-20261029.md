# 五场景真实展示链联调（2026-10-29）

状态：真实模拟退款闭环已执行；完成后追问发现客服答复与退款回执矛盾，整体验收暂不通过，正在修复。

用户授权真实模型和实际操作验证，不设本轮请求次数上限。范围为一条本地演示订单的五场景闭环，不开展额外批量评测；保留生产Harness的单run权限、预算和终止规则。真实模型与本地模拟资金/物流分别标识，不以合成截图替代本次运行，不清库或重做基础数据。

验收口径：商品/规格/金额一致；实际模型按订单事实通俗答复，实际等待及流式回复可结束；退款摘要由买家核对并显式确认；商家按当前权限核验/审批；真实本地退款操作成功后聊天、申请和订单状态/金额一致。理解、事实、权限和能否操作为阻塞项，轻微措辞与审美偏好为非阻塞建议。已有异常边界由原自动化检查覆盖，本轮不为文案清零重复收费。

启动前只读检查：原8工单为5 CLOSED_SUCCESS、3 PENDING_REVIEW；36咨询run为29 SUCCEEDED、7 FAILED，无待处理咨询；原9调查绑定全部DISPATCHED，PG调查8 COMPLETED/1 FAILED，无QUEUED；5退款操作全部SUCCEEDED；两端事件Outbox共10条PUBLISHED，18回调DELIVERED。没有遗留待自动推进的旧任务。沿原MySQL/PostgreSQL/Redis/RocketMQ卷启动，不执行reset。

准备与最终结果、实际模型请求/usage、订单/申请/退款身份及失败会在本文件后续追加。原始响应、截图与运行日志仅本机tmp/display-chain-live-20261029保存，提交记录不含访问令牌或密钥。

## 已执行与阻塞

buyer09通过正式网页新买无线降噪耳机黑色一件，实付32900分。订单`bb1eb1cf-4720-428c-8179-6ef93ce6fe70`、订单行`SHOP-6ec5216c-61b5-431a-8a9f-e87dc05d1f2d`；商家网页模拟发货后，仅对本行用物流模拟器追加LOST事件，原数据和政策版本保持。

两轮真实咨询分别查询物流、准备退款草稿；买家确认前本行0工单，编辑原因并显式确认后创建`80ac23d2-2fbd-4b4c-88ec-a6a1e41a9534`。首轮调查`e7d27170-126f-5229-a6f9-42744ec65a4b`转人工；商家核验材料后revision2调查`9e620607-c345-5855-b034-cb8bd8eb2876`引用R-LOST-001提出REFUND，商家网页独立批准。同一退款操作`c3dbfd77-0d9c-4ec4-b6e9-e62c8636cff9`成功32900分，模拟provider记录1次请求；Java账本已退32900、预留0。聊天卡、独立详情和订单均可查看完成结果。原8工单、5退款及36咨询的基线所采字段逐条保持，不等于全库所有字段快照比较。

发现并修复：CustomerCaseService先判断授权已消费，再判断终态，导致完成仍返回“进入执行阶段”。改为终态优先，只修正公开说明，allowed_actions和金额保持。CustomerWorkspaceApiTest新增完成状态及已消费失败状态对照，先1项失败，再全类9项通过；当前2文件定向Spotless与package通过，Case重启后实际回执已显示“申请已结束，仅可查看记录”，16px正文、1280×720无横向溢出。截图`tmp/display-chain-live-20261029/13-live-refund-receipt-fixed.png`。

真实质量失败保留：首调查检索query“包裹丢失 物流未送达 退款 商家审批 条件”返回INTRANSIT/DMG/UNSHIPPED，遗漏LOST；模型扩大解释DMG为也支持丢失。该轮MANUAL_REVIEW不产生退款授权，不能把引用身份校验VALIDATED当语义正确。第二轮query变化后返回LOST并正确引用，但不抹去首轮质量失败；本轮未改政策、索引或固定问法来追单题满分。

新增阻塞：退款完成后问“现在这笔退款办好了吗？退了多少钱，还需要我做什么？”，run `0a70b285-aaed-4086-ab8f-e072eadb8bcd`回答“还没有办好，目前没有已提交或已退款的记录”，与真实CLOSED_SUCCESS相反。实际工具order仅有原付款商品信息，shipment/policy没有退款执行事实；conversation_state.has_ticket指独立咨询核查单，并非退款申请。正在核对只读事实接入与答复约束，不能仅改措辞或将has_ticket=false解释为没有退款。

截至前两咨询+两调查共17次真实DeepSeek请求，provider报告input42174/output1662 tokens、非估算；第三次追问另计，最终汇总后追加。真实模型、模拟资金及合成物流明确区分。

实际失败命令：初次Maven参数未整体引用导致生命周期解析失败；全模块Spotless发现ReviewerRunInput、ReviewerRunInputTest、OrderApiTest既有格式问题，未顺手修改；定向参数先误用glob后改正则；首次package因Windows运行JAR锁失败，仅停止所属Case后重建成功。Case启动中一次刷新返回500，健康后恢复。原始失败日志保留，不算业务或模型成功。
