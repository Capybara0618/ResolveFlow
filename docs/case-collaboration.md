# 工单协作协议

业务规则来自[双端与多人协作方案](product-completion-review.md)模块三，对应[v2交互合同](ui-targets-v2/README.md)。实施状态只看[todo顶部](../tasks/todo.md)；本文规定当前协作与人工写入协议。

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

版本每次真实变更加一，释放后重新领取也不重置，防止转交给别人再转回来时旧页面重新获得写权限。该接口不取消原退款授权，不改变政策/金额，不让管理员绕过人工动作原有状态与授权校验。人工写入口与桌面归属操作使用以下统一凭证；人员管理与队列范围仍按第三批后续合同实施。


## 人工操作凭证与桌面交互

工作人员对`evidence`、`reviewed-evidence`、`cancel`、`manual-proposals`、`review-actions`和`reviews`提交时，必须已经是当前负责人，带原始读取的`If-Match`（工单版本）和`If-Collaboration-Match`（协作版本）。工单锁内同时检查两版及入口捕获的签名身份版本；他人、未领取、转交后旧页面及缺失协作凭证409。非法正文/版本格式422；`reviews`沿用原有缺失If-Match返回422，其他人工入口缺失业务版本409。客户追加材料、回答与撤销保持本人范围/期限/消费冻结协议，不使用负责人凭证；Agent回调和执行结果不采用人工凭证。

GET collaboration增加`is_owner`，按当前主体判断，不能仅看角色或allowed_actions推断审批权。管理员可通过CLAIM领取未领取工单，已有负责人时须显式TAKEOVER或转交给自己；然后才可核验、补证、形成人工方案或审批。V22仅追加修正旧角色CHECK和actor列120字符兼容，保留原约束；模型仍无这些写权限。

`GET /api/v1/review/staff`仅向本商家工作人员返回启用工作人员的username/display_name/role/enabled，供转交选择；无客户、口令、哈希或其他商家资料。身份创建/维护不是这个只读目录的权限。

审批的Commerce复核、人工方案的来源/政策复核均先在事务外执行；随后在工单锁事务内复查读到的业务版本、协作版本、当前授权及身份。期间转交/补充材料使提交409，复核结果不落库，不能自动替换成新版本重试。最终可退金额仍由Commerce在执行时权威判断。

桌面CaseAssignment显示真实负责人和协作历史；领取/释放/转交/接管须理由，目标来自真实人员目录。审核/人工方案弹窗保留打开时的两版，409后关闭并刷新；迟到人员列表不能污染切换后的工单。负责人变化当前通过“刷新归属”或冲突响应刷新，不宣称已有跨会话主动推送。协作变更本身不增加业务版本、不创建Agent调查；客户回答和核验仍可正常推进修订，负责人保留。
