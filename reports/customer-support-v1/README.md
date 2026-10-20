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

## 网页与保留数据跨进程验收

用户端在商城新增“售后咨询”，商家工作台新增“咨询核查”。统一SupportWorkspace按角色分别读取本人会话与本店共享投影；确认转交预览、显式消息接收方、商家补问/回复、客户补充/解决都使用真实API。原请求与幂等键在sessionStorage按主体保存，未知结果只能原请求重试；版本冲突保留输入/要求重新确认。读取更早历史时暂停自动刷新。

网页全套Vitest 25文件/189项通过，vue-tsc类型检查及Vite正式构建通过。新测试覆盖确认前不提交、原文ID范围、响应丢失同请求重试、旧版本不重发、商家投影及A晚响应不覆盖B；已有商家导航断言只添加新增“咨询核查”，原行为断言保留。

真实保留环境：先备份Case到忽略目录`tmp/customer-agent-design-v1/case-before-v27.sql`，V27正常Flyway应用，Commerce保持V16；旧Case5/授权4/槽5、Commerce订单12/行12/账本12/行退款12/退款操作4的全表排序hash前后相同。临时Case/Commerce关闭派发/MQ/outbox投递/退款后台，Python不启动，网页直接代理Case，Gateway未重验。

`scripts/customer_support_acceptance.py`执行一次及同一状态重放一次，各26个真实HTTP调用通过。两段会话/一个核查单；共享一条原文、两条私人记录不交商家，商家补问→客户三次补充→商家回复→客户解决；相同key原响应、不同载荷409、跨店/跨买家404、商家读私有会话403、三个真实响应符合共享契约。证据为[运行JSON](runtime-check.json)，不提交原始令牌/数据备份。

`scripts/check_support_runtime.cjs`使用既有Edge/Playwright登录双端，真实投影与转交预览检查通过；4视图×3种宽度共12项无横向溢出、3项样式检查、无JavaScript页面异常，[浏览器JSON](browser-check.json)及[实图](../../docs/customer-support-workspace.md)可查。人工检查发现旧全局工作台/商城CSS影响历史卡片、按钮与勾选框，已通过本模块具体选择器隔离并重拍；没有仅凭溢出检查宣称视觉通过。

本批前端红测先因组件未实现失败，后续Headers对象测试改为真实Header读取、旧导航精确数量同步新增入口；临时文本替换命令引号失败未写文件。完整契约回归最终94通过/1既有断言失败，聚焦18项与新增Java/Web检查全部通过，失败未隐藏。

[前端与来源检查](frontend-check.json)保存189项测试计数、88个本地链接、9份源码及4张PNG哈希；[收尾检查](cleanup-check.json)确认3个所属临时进程和端口关闭，MySQL/卷/数据保留。实际代码/测试/截图及脱敏报告提交，备份/幂等请求/原始日志保持忽略，不覆盖原4个脏文件或旧资产。
