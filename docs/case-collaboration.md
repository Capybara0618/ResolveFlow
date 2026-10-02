# 工单协作协议

业务规则来自[双端与多人协作方案](product-completion-review.md)模块三，对应[v2交互合同](ui-targets-v2/README.md)。实施状态只看[todo顶部](../tasks/todo.md)；本文规定接口，不代表所有人工入口已经接入负责人检查。

## 独立记录

Case V21增加`case_collaboration`和`case_collaboration_event`。历史工单没有协作行时返回`owner:null,version:0`，不批量分配。协作版本独立于case.version、input_revision和authorization_version。领取、释放、转交、接管仅更新协作表，不写业务时间线、Outbox或Agent binding；客户回答、新材料和调查不修改负责人。

## 读取和动作

`GET /api/v1/cases/{case_id}/collaboration`仅向本商家工作人员开放，返回`case_id/version/owner/allowed_actions/history`。owner包含稳定username、当前display_name、role、enabled；历史记录保存稳定actor/from/to用户名和理由，不重写历史身份。跨商家和不存在统一404，客户403，失效会话401。

`POST`同一路径，body为`{action,reason,target_username?}`，`action`支持CLAIM/RELEASE/TRANSFER/TAKEOVER。`If-Collaboration-Match`必须为带引号的非负协作版本，例如`"0"`；缺失或过期409，格式错误422。理由1–1000字；只有TRANSFER接受且必须提供目标用户名。

- CLAIM：未领取工单由当前工作人员领取；同一人重复请求返回当前归属，不再增加版本或历史。重复请求仍检查有效会话、可协作状态、合法版本头及理由。已被别人领取即使管理员也不能用CLAIM覆盖。
- RELEASE：负责人或本商家管理员释放，目标为空，保留记录。
- TRANSFER：负责人或管理员转交给本商家启用的工作人员；不存在、客户、禁用或其他商家账号统一422，不泄露其资料；目标与当前负责人相同422。
- TAKEOVER：仅管理员，显式将负责人改为自己，须理由及当前版本。专员403，已是负责人409；不是审批操作。

授权尚未批准且未消费时，QUEUED/ANALYZING/WAITING_CUSTOMER/PENDING_REVIEW可协作。AUTHORIZED、执行/对账/终态和任何存在CONSUMED授权的工单均409，保留最后负责人。禁用负责人仍展示，管理员可对可协作工单释放、转交或接管。OPERATOR沿用本地工作人员兼容身份，不能使用管理员接管权限。

## 并发边界

动作短事务依次锁工单行、所属商家共享锁、按用户名排序的相关账号共享锁，再写协作记录。相同工单的操作串行；账号锁内重新核对启用状态、商家、角色、客户绑定和入口捕获的签名identity_version，密码重置/禁用不能靠入口检查与写入之间的时间差通过。无网络、模型或退款调用。后续人员管理只能更新本商家账号，不锁工单，须沿用兼容锁顺序。

版本每次真实变更加一，释放后重新领取也不重置，防止转交给别人再转回来时旧页面重新获得写权限。该接口不取消原退款授权，不改变政策/金额，不让管理员绕过人工动作原有状态与授权校验。所有人工写入口接入和桌面UI属于同一第三批的后续子步，不能以本接口测试代替整批验收。
