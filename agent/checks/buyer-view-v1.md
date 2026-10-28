# 买家正文与办理展示分层（2026-10-28）

用户要求助手完全从买家体验出发，并授权把正文、按需指引与操作卡片职责分开。本批沿用唯一AgentScope循环、Java金额/权限/确认与既有Vue布局，不增加润色模型，不使用关键词删句，不新增付费请求。

## 协议与Java接收

新增可选`buyer_view`，版本`buyer-view-v1`，1–8个事项，每项仅task_id/text、可选guidance或action。action仅REFUND_APPLICATION/MERCHANT_REVIEW，是展示提示，不代表草稿就绪或执行授权；guidance与action不同时出现。兼容历史消息缺字段，原text保持为展示各段text/guidance的完整连接文本，避免历史/共享和屏幕正文不一致。内部字段、未知版本/动作、重复事项/动作、缺少对应原因或隐藏替换文本均被Java拒绝。

SupportAgentTurns校验后写入既有assistant_json；SupportWire持久读取该字段，商家确认共享报告仍仅原allowlist，不带买家展示信息或退款原因。无需数据库迁移。Python生产者和前端消费按后续小步接入，当前接收可选字段不改变旧客户端行为。

验证：新契约4项先因缺Schema失败，新增Schema/fixture后相关12项通过；Java新4单元及新2持久HTTP检查（连同继承31项）共37项通过，使用Testcontainers隔离MySQL，不动演示业务库。新增字段持久可读、未创建草稿/Case、跨买家拒绝、商家私聊拒绝、共享报告不泄漏和畸形展示不发布均有断言。命令：`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am '-Dtest=SupportBuyerViewTest,SupportBuyerViewApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test`；`pnpm --dir web typecheck`、限定本批Java文件的Spotless及diff-check通过。

首次PowerShell未引用含点的Maven属性，解析为错误phase，测试未执行；修正引用后37项通过。首次Spotless使用glob但该属性需要regex，明确失败后只对本批文件按regex格式化，不改原脏文件。日志tmp/support-buyer-view-*.log保留，失败不计通过。
