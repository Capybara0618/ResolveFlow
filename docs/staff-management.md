# 本商家最小人员管理

按[已批准双端方案](product-completion-review.md)模块五、[v2人员页](ui-targets-v2/README.md)实施，复用[持久身份](persistent-identity.md)，不增加IAM、公开注册或跨商家管理。

仅当前启用MERCHANT_ADMIN可调用以下接口；账号所属商家来自会话，不接受正文merchant_id/customer_id/username改名。工作人员/客户403，失效会话401，其他商家与不存在目标统一404。Agent服务令牌不具备管理权限。

| 接口 | 合同 |
| --- | --- |
| GET /api/v1/admin/accounts | query（username/显示名包含文本≤100）、role（ALL/CUSTOMER/REVIEWER/MERCHANT_ADMIN/OPERATOR）、status（ALL/ENABLED/DISABLED）、limit（1–100，默认20）、cursor；返回items/page/total/enabled_admins/current_username。total按全部筛选统计；enabled_admins为本商家全量启用管理员数。游标≤256字符，绑定商家、当前账号和筛选 |
| POST /api/v1/admin/accounts | username（全局唯一，1–120位字母数字及`.`/`_`/`-`，首位字母数字）、display_name（1–120）、role（REVIEWER/MERCHANT_ADMIN）、password（8–200且不全为空白）、reason（1–1000）。201返回account/session_invalidated=false；重名409且不透露归属；客户和OPERATOR沿用种子，不通过本入口新增 |
| POST /api/v1/admin/accounts/{username} | display_name/role/enabled/reason，If-Match为打开维护时的account.version。只允许REVIEWER↔MERCHANT_ADMIN，CUSTOMER/OPERATOR只能保留原角色；显示名/启停可维护。真实修改推进account.version；无变化不写审计。最后一个启用管理员不可禁用/降级409 |
| POST /api/v1/admin/accounts/{username}/password | password/reason及原If-Match。每次成功使用随机盐PBKDF2-SHA256/120000轮，推进account.version与identity_version；不回读或记录密码/哈希。旧版本409，缺版本409，格式错误422 |
| GET /api/v1/admin/accounts/{username}/history | 本商家目标的审计，按id倒序cursor分页；每条actor/动作/理由/时间/维护版/公开前后状态，含CREATED/UPDATED/PASSWORD_RESET，无密码/哈希/旧会话token |

V23只追加account_version及账号审计表。账号维护版本与identity_version分开：显示名真实修改只增维护版；角色/启停/密码成功变化同时增身份版，重新启用不能复活旧token。稳定username、merchant/customer绑定不改变，人员维护不释放工单、不增业务修订、不新建run。管理员对自己进行安全字段变更时返回session_invalidated=true，网页立即退出；修改自己显示名只更新页头。

管理写事务先锁本商家FOR UPDATE，再按稳定用户名顺序锁本商家相关账号，锁内复核入口签名身份版本、role/绑定/enabled；不反向锁工单。商家锁序列化启用管理员数的检查与写入，防止两个管理员同时各停用自己。密码计算在进入短事务前进行，审计与账号写同事务。与现有case→merchant共享锁→有序account共享锁兼容；已进入旧SSE连接仍不承诺立即关闭。

正式桌面菜单仅管理员显示人员管理；沿用共用页头/侧栏、白蓝表格与维护侧栏，新增/重置用现有对话框。显示真实筛选总数与cursor加载更多，不伪造页数。维护保留打开时版本；409刷新列表、保留非密码草稿并禁止按新版本自动重发，重新打开后核对。密码不持久化，提交/退出后清空；请求结果未知只提示读取现状，不自动重试。切换页/账号与迟到响应不能污染当前人员页。

验证重点：新增登录/领取、双商家和角色拒绝、分页/游标/真实总数、旧会话失效及重新启用、显示名不会杀旧会话、并发维护/最后管理员/签名失效窗口、审计无凭据、人员变化保留工单负责人。实际进度只看[todo顶部](../tasks/todo.md)。
