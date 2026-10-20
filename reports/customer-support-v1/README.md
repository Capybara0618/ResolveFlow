# 客服会话与人工核查：实施证据

2026-10-20。承接[协议](../../docs/customer-support-contract-v1.md)与[预期图](../../docs/ui-customer-agent-v1/README.md)。进度只在[todo顶部](../../tasks/todo.md)维护。

## 后端

Case追加V27四张独立表：support_conversation/message/ticket/receipt；新增SupportController/Service，沿用平台买家归属和商家身份。会话按buyer/line恢复，所有写入事务内检查账号与版本，幂等回执/消息/状态同事务。写事务READ_COMMITTED配合会话锁，防止并发等待后仍读旧快照；读取保留一致快照。跨进程Commerce归属查询在事务外，商家只读共享原文快照及公开核查消息。

原退款Case/资金表、派发和Agent循环不参与咨询；没有伪case_id或模型调用。单核查单支持PENDING/WAITING_CUSTOMER/REPLIED/RESOLVED，客户补充可重开，咨询不套用退款补证两轮上限。

Java实际验证：隔离Testcontainers MySQL8.4完整迁移V1–V27，SupportApiTest 8项、共享Wire往返1项、既有PlatformBuyerApiTest 8项与CheckoutBuyerApiTest 4项，共21项通过，0失败/跳过。HTTP测试中的Commerce为按真实主体过滤的stub；该结果不是保留演示库的跨进程验收。

```powershell
.\java\mvnw.cmd -f java/pom.xml -B -pl case-service -am '-Dtest=SupportApiTest,SupportWireTest,CheckoutBuyerApiTest,PlatformBuyerApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
.\java\mvnw.cmd -f java/pom.xml -B -pl shared-kernel,case-service '-DspotlessFiles=.*Support.*\.java' spotless:check
```

协议同步：Case核心OpenAPI新增9操作/12个Support组件，共享Java record、9份JSON fixture和Python验证；核心路由表/数量断言70→79，原路由断言保留。新协议/本地引用/路由重复聚焦检查18项通过，Ruff通过。

完整核心路由回归发现旧`test_the_line_context_is_where_the_amount_is_recomputed_from`的可选字段断言未包含Commerce既有payment_version/fulfillment_status/fulfillment_version。Commerce契约与该断言函数均与本批前HEAD一致，本批保留失败，不删除断言或修改资金协议来通过。详见结构化核验记录。

开发失败及修正：红测6项因support表不存在失败；首次PowerShell Maven -D参数未引号、Spotless将glob当正则均已修正；共享Wire测试曾遇到泛型断言歧义、IntNode/LongNode比较差异，改以序列化JSON往返比较；初版生成错误响应引用重命名错误已修正，所有本地引用重新通过。日志保留忽略目录`tmp/customer-agent-design-v1/support-*`，不提交原始日志/令牌或数据库快照。

## 验收边界

本批提供持久咨询与人工接续，不声明智能问答、调查报告自动生成、RAG新效果或客服入口退款确认已完成。后续Agent必须按conversation输入版本发布，咨询无Case时采用独立只读身份，不可直接复用拥有Case权限的凭据；退款仍需客户确认和Java复核。未运行收费模型与旧量化实验，Gold/简历保留。
