# 聊天退款核验衔接修复（2026-10-23）

按用户授权修复确认原因、正常待核验调查与状态展示，保留[原真实失败](../chat-refund-live-v1/README.md)。本轮新状态仅见tasks/todo顶部。

## H1 确认原因进入初始材料

SupportRefundService复用EvidenceRepository，仅新建Case时将最终确认原因原样登记为revision1的CUSTOMER_STATEMENT，来源绑定客户/会话/草稿、版本绑定会话输入版与草稿revision、hash覆盖文本和主体；无核验结果。与Case/run/确认关联/回执同事务，草稿编辑取消/已有单接续/重放不添加材料。沿原派发evidence_refs和review_context读取，无第二轮建单或初始revision2。

V32追加迁移只允许初始revision1为未核验客户陈述，人工核验仍在后续revision；历史迁移/记录保持。商家实际核验接口对CONFIRMED/REFUTED/INCONCLUSIVE均能引用该初始陈述、保留原文、创建revision2及新调查binding。

实际验证：JDK21，java目录`./mvnw.cmd -B -pl case-service -am -Dtest=SupportRefundApiTest,SupportRefundWireTest,EvidenceApiTest,ReviewedEvidenceApiTest,AgentRunDispatchApiTest -Dsurefire.failIfNoSpecifiedTests=false test`（PowerShell两个-D参数均整体加引号）。真实隔离MySQL/Flyway/HTTP：Case68通过（确认43、原材料8、人工核验9、派发8），shared DTO2通过，0跳过，reactor56.578秒。限定SupportRefund格式通过，git diff --check通过。

失败记录：最初Maven未整体引号导致-D参数被拆，不计测试；新两项红测均失败。初实现触发原revision>=2约束（40项4失败1错误），追加V32；之后测试异常分类预期不符（40项1失败），改为断言真实DataAccessException根因CHECK名字；扩测68项4失败为客户投影未暴露revision、旧多人fixture未领取，分别改DB断言及显式生产领取，再全组通过。不删既有断言、不修改旧迁移、不降低核验条件。额外一次补丁因格式化后上下文不匹配未写入，定位后修正。

本步未重启/迁移原项目、未写原业务库或调用Provider，原usage2076；四历史脏文件排除。后续H2调查上下文/纠错与有效人工复核建议，H3双端状态和集中链路确认。
