# 第四批：商家概览、政策阅读与桌面状态

依据已批准的v2图10/12和实施合同，复用现有客户、归属、审核及人员管理，不增加管理平台、消息中心或政策写入口。

管理员新增三个只读接口：GET `/api/v1/admin/overview`、GET `/api/v1/admin/policies`、GET `/api/v1/admin/policies/{bundle_id}`。仅当前有效本商家MERCHANT_ADMIN会话；跨商家政策与未知政策同为404。概览在一次MySQL读快照内统计全部本商家工单，返回最多20条需协调记录及真实总数，不将当前页长度当总数。

概览未领取指尚无负责人、处于QUEUED/ANALYZING/WAITING_CUSTOMER/PENDING_REVIEW且未消费授权的工单；我的待办指本人负责的未结束工单。需关注是未结束且退款RECONCILING、负责人停用/不再具有工作人员角色，或当前输入版收到ACCEPTED FAILED回调且尚无VALIDATED方案的并集。理由可以重叠，工单只计一次；历史失败不累计到新修订。概览不提供隐式分配/接管/审批，进入原详情后按现有权限操作。启用工作人员计数包含REVIEWER/MERCHANT_ADMIN/兼容OPERATOR。

政策列表只展示已有不可变bundle的版本、有效区间、导入时间、规则数量和manifest hash，不暴露本地source_path。按生效起点降序，最多100条并明确truncated。详情返回原文、规则/块编号与内容hash。区间包含当前时间仅表示覆盖当前时间；实际工单仍按支付时间选择并钉住版本，不将旧工单替换成最新政策。

索引状态由Python拥有，新增内部GET `/internal/v1/policies/{bundle_id}/index-status?manifest_hash=...`，要求case-service服务身份、policy:read scope及merchant claim。仅查该商家该bundle和精确hash的持久generation，不调用模型、embedding或构建索引。READY优先，否则最新BUILDING/FAILED，精确版本缺失为MISSING；不可用由Case详情投影为UNAVAILABLE。Case先验证政策归属再发请求，使用现有有界只读客户端，不在持有数据库事务期间等待网络。未实测状态不能显示为READY。

桌面新增管理员概览/政策导航，专员公共/我的/结果待确认/历史快捷入口仍走现有队列筛选。可见且空闲时周期读取发现新工单，保留搜索草稿与审核弹窗，不自动切换所选工单；分页展开时仅更新计数并提示刷新，避免静默丢失已加载行。客户申请列表周期更新，填写申请/回答/追加材料期间不切换页面或清理草稿。401退出失效会话；请求失败保留原数据并提供重试，迟到响应不写入其他账号/页面。

集中验证范围：真实MySQL权限/计数/隔离/原文/无写入；Python索引精确hash/商家/状态与服务鉴权；核心路由/类型/fixture同步；前端导航、周期发现、迟到保护与失败空态；1280/1440/1680桌面浏览器。此批不触发收费调查或新增模拟退款；第五批再做跨角色完整流程验收。
