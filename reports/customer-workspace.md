# 客户完整申请实施与验证

2026-10-02，新第二批。复用此前未提交客户接口原型、持久身份、原订单/材料/撤销及工作人员业务，不重做身份迁移或Agent循环。页面对应v2的02–06/17；当前详细进度仅在tasks/todo.md顶部维护。

## 客户接口收口

- 新增本人分页列表、客户最小详情、订单行资格和带If-Match的当前问题回答，共4个客户路由；新增V20两项索引，旧迁移及数据保留。服务器按JWT的merchant/customer过滤，工作人员访问403，其他客户/商家详情404。客户投影没有方案、授权、模型/工具原文或工作人员actor。
- 问题截止为事件发生后72小时与持久工单期限的较早者，新旧材料入口均拒绝过期回答；问题ID/工单版本自动由客户端关联。回答仍走原材料事务，增加修订并产生新调查绑定。
- 修复创建幂等重放泄露：先核对原工单归属，再比较请求体，竞争重放路径同样受保护。已消费且返回审核/等待状态的申请依然只读；明确执行失败采用原operation匹配的非陈旧持久事件给出公开说明。
- 核心路由表及OpenAPI同步新增4条（Case22→26）。修复原型分段生成的YAML锚点重名，保留旧模式和所有断言；客户响应/请求例子进入既有契约校验，并测试客户投影拒绝内部成员及回答版本格式。

实际验证：Java21，Maven `-pl case-service -am -Dtest=CaseApiTest,CustomerWorkspaceApiTest,EvidenceApiTest,CaseCancelApiTest,ManualProposalApiTest,ReviewerActionsApiTest -Dsurefire.failIfNoSpecifiedTests=false test`，实际运行前5个存在的类共50 passed（9/7/8/8/18），最后指定名不存在、没有运行，不将其计为通过。Python `-m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py -q`：121 passed。定点Spotless apply覆盖8个本批Java文件，实际清洁8文件；不格式化Commerce他人改动。

失败和修复：权限失败回归先6项中1 failed（另一客户实际拿到201），修复后上述50通过；契约原型先38 failed/33 passed（锚点重名及路由数），修复后71通过，再加入投影检查首次因错用ValidatorBundle.iter_errors得到1 failed/120 passed，改用既有accepts/error_messages后121通过。消费测试首次fixture直接插CONSUMED违反审批CHECK，修为先建待审、记录批准再标消费后通过，不把无效fixture当有效RED。初始Maven未引用带点参数、Spotless误用glob和经cmd解释的管道正则导致命令失败，后改为引用参数及逗号分隔无管道正则；无效命令不计通过。临时日志在忽略的tmp目录，未提交原始敏感运行日志。

本段完成接口与相关回归；客户页面和正式浏览器闭环正在本批接续，未据此宣称新第二批整体验收完成。没有调用收费模型、批准演示历史申请、清库或删卷。
