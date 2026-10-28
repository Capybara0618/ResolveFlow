# 买家正文与办理展示分层（2026-10-28）

用户要求助手完全从买家体验出发，并授权把正文、按需指引与操作卡片职责分开。本批沿用唯一AgentScope循环、Java金额/权限/确认与既有Vue布局，不增加润色模型，不使用关键词删句，不新增付费请求。

## 协议与Java接收

新增可选`buyer_view`，版本`buyer-view-v1`，1–8个事项，每项仅task_id/text、可选guidance或action。action仅REFUND_APPLICATION/MERCHANT_REVIEW，是展示提示，不代表草稿就绪或执行授权；guidance与action不同时出现。兼容历史消息缺字段，原text保持为展示各段text/guidance的完整连接文本，避免历史/共享和屏幕正文不一致。内部字段、未知版本/动作、重复事项/动作、缺少对应原因或隐藏替换文本均被Java拒绝。

SupportAgentTurns校验后写入既有assistant_json；SupportWire持久读取该字段，商家确认共享报告仍仅原allowlist，不带买家展示信息或退款原因。无需数据库迁移。Python生产者和前端消费按后续小步接入，当前接收可选字段不改变旧客户端行为。

验证：新契约4项先因缺Schema失败，新增Schema/fixture后相关12项通过；Java新4单元及新2持久HTTP检查（连同继承31项）共37项通过，使用Testcontainers隔离MySQL，不动演示业务库。新增字段持久可读、未创建草稿/Case、跨买家拒绝、商家私聊拒绝、共享报告不泄漏和畸形展示不发布均有断言。命令：`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am '-Dtest=SupportBuyerViewTest,SupportBuyerViewApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test`；`pnpm --dir web typecheck`、限定本批Java文件的Spotless及diff-check通过。

首次PowerShell未引用含点的Maven属性，解析为错误phase，测试未执行；修正引用后37项通过。首次Spotless使用glob但该属性需要regex，明确失败后只对本批文件按regex格式化，不改原脏文件。日志tmp/support-buyer-view-*.log保留，失败不计通过。

## Python生产者

生产navigation不再把程序教程拼入正文，旧模式默认保持。新增guidance作为模型的可选操作说明通道，仅活跃EXPLAIN且已声明GUIDE时可见，操作卡、来源失败、暂停/撤回/结束事项不展示；必要客户追问必须在正文，不能藏进被省略的guidance。按事项分别处理，多问题中的独立指南问题不会被同轮退款卡吞掉。grounding与金额校验覆盖可见guidance；本轮有效原因、已验证来源和资金/权限门禁不变。

presentation.py在最终校验成功后从程序已接受目标/步骤构造buyer_view；模型不能直接指定buyer_view/action。顶层text连接可见text/guidance，和Java一致性规则相同。程序不承诺卡片已就绪，前端仍读Java真实状态。新manifest标buyer-view-v1并纳入新文件hash，不升级旧run。流式白名单只投影parts.text，guidance、原因和动作不提前流出。

新7职责测试先5失败/2通过，实施后通过，补多事项/三种停止状态/来源失败共12项通过。第一次实现遗漏AnswerPart导入，测试/静态检查明确失败后修正。原5项依赖“程序在text追加教程”的断言改为正文不变和独立action，原确认/共享/失败/预算断言保持。最终`python -m pytest agent/tests/unit -q -rs -k 'support or buyer_language_smoke'`：601通过、8按原fixture无citation条件跳过、2044未选；Ruff/diff通过。

旧v3完整6轮+定点3轮原始决策经最终生产循环离线重放全部可发布，buyer_view通过Schema、正文连接一致，记录tmp/support-buyer-view-recorded-replay.json。0新增模型请求，账本3619不变。它只验证新协议/门禁兼容：旧模型本来写在text里的办理教程仍原样保留，没有关键词删句，不把重放当作新模型自然表达已达标。
