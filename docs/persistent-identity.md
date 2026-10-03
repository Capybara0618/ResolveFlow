# 本地持久身份与双商家数据

2026-10-03新增[平台买家协议](platform-buyer.md)：旧商家客户与工作人员绑定继续保留；新平台买家只携带buyer_id，跨店本人范围由可信复合映射决定，沿用本文件同一登录/版本校验机制。`demo-buyer / demo-pass-4001`是新的合成账号，不自动继承下表客户的历史订单；商家管理员不能管理平台买家凭据。

本文件说明双端方案第一批的身份基础。实施状态与证据见[todo顶部](../tasks/todo.md)，业务范围见[双端方案](product-completion-review.md)。

## 账号与权限

Case的`identity_merchant`、`identity_account`是用户身份权威，登录不再查询Java固定账号列表。稳定username继续作为JWT subject和历史actor，merchant/customer绑定保持原值。新增账号只需持久化到这两表，不需修改Java常量；第三批已接通管理员创建、禁用、角色和重置账号API，正式网页与批次验收见[人员管理](staff-management.md)及[实际记录](../reports/staff-management.md)。

密码保存PBKDF2-SHA256 hash，沿用120000轮的现有格式。未知账号、错误密码、账号或商家禁用统一返回401；登录与`GET /api/v1/auth/me`只返回公开身份字段，不返回hash。username不是可随意修改的展示名。

| 角色 | 第一批权限 | 后续规则 |
| --- | --- | --- |
| CUSTOMER | 本商家本人订单和工单，原有客户操作 | 第二批补客户专用投影、列表与问题页面 |
| REVIEWER | 本商家审核读取与原有人工操作 | 第三批人工写入需当前负责人及协作版本 |
| MERCHANT_ADMIN | 本商家工作人员读取；领取/显式接管后的人工操作 | 当前负责人、业务/协作/签名身份版本均通过才可处理，继续验证金额/状态 |
| OPERATOR | 原本地运维兼容角色，限定本商家 | 不作为普通多人演示账号，无跨商家超级权限 |

## 会话失效与入口

登录JWT增加整数`identity_version`；历史不带该字段的用户JWT按0兼容。Case每个公开受保护请求验证JWT后，读取当前账号/商家，校验enabled、identity_version、role、merchant_id、customer_id；未知subject或绑定不符也拒绝，不能仅凭有效签名获得不存在的身份。

禁用阻止之后到达的请求和新登录。禁用、密码重置或身份变更的受控管理操作必须递增identity_version，重新启用不能恢复旧token。角色/商家/customer变化即使遗漏递增，也因逐项比对拒绝旧声明。检查发生在请求入口，**不承诺取消已经开始的事务或关闭已经建立的SSE连接**；显示名变化不产生调查修订。

公开`/api/v1/**`由Gateway转到Case，直接访问Case也经过同一resolver。订单读取以校验后的身份生成Commerce内部SERVICE凭证；Commerce仍拒绝USER JWT和未授权scope。没有新增跨库读取或把用户token当内部权限。Agent内部凭证沿用独立scope/fence，不纳入用户账号表。

## 合成账号

以下是本地演示凭证。正常启动`.\demo.ps1`应用追加迁移，stop保留账号和历史数据。

| 商家 | 角色 | username | 演示密码 | customer |
| --- | --- | --- | --- | --- |
| M-1001 | 客户 | demo-customer | demo-pass-1001 | C-2002 |
| M-1001 | 客户 | demo-customer-2 | demo-pass-1002 | C-2003 |
| M-1001 | 审核员 | demo-reviewer | demo-pass-1003 | — |
| M-1001 | 审核员 | demo-reviewer-2 | demo-pass-1004 | — |
| M-1001 | 管理员 | demo-admin | demo-pass-1100 | — |
| M-1002 | 客户 | demo-customer-m2 | demo-pass-2001 | C-2004 |
| M-1002 | 客户 | demo-customer-m2-2 | demo-pass-2003 | C-2005 |
| M-1002 | 审核员 | demo-reviewer-m2 | demo-pass-2002 | — |
| M-1002 | 审核员 | demo-reviewer-m2-2 | demo-pass-2004 | — |
| M-1002 | 管理员 | demo-admin-m2 | demo-pass-2100 | — |
| M-1001 | 原本地运维 | demo-operator | demo-pass-3001 | — |

## 迁移与政策

Case V19只新增身份表和种子，保持原六账号subject、密码hash及绑定，不回写历史工单。Commerce V8新增M-1002/C-2005独立订单、7301订单行、22900分支付账及模拟LOST物流；原订单、退款与预留记录不变。两个商家各有两位可查询订单的客户。

新增`policy-demo-m1002-logistics-2026.08`与`.09`，按本商家和支付时间选择。原M-1001及M-2002损坏政策、已绑定manifest不改名、不改hash；M-2002保留为历史政策测试样本，不是第三个可登录的演示商家。演示驱动导入新增fixture并建立其索引；只读启动不调用模型。

第三批管理实现必须复用该身份数据和版本规则，不能重新引入固定Java账号、用缓存放过禁用会话、接受请求merchant扩大范围，或把管理员角色等同于已领取工单。
