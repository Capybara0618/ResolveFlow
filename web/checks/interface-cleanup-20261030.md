# 全站文案精简与首页调整（2026-10-30）

用户要求移除无助于操作的辅助说明，改善登录首页和商城首页。按界面小步处理，不改变身份、金额、授权、订单或退款逻辑。

## 入口与首页

`App.vue`移除全局演示标签、登录副说明、身份范围提示和侧栏口号；保留字段标签、登录/注册/找回和商城入口。登录页改为双栏：主标题与现有生活场景图、独立登录表单，390px下仅显示表单。`interface.css`统一间距、48px输入和按钮，`MarketplaceWorkspace.vue`删除全站商城说明页脚，`marketplace.css`调整首页主视觉、标题字重和明确的浏览按钮。

命令：`pnpm --dir web test -- tests/app.spec.ts tests/marketplace.spec.ts`，最终35项通过；`pnpm --dir web build`类型检查/生产构建通过。首次静态img地址在Windows Vitest转换成file:///marketplace路径导致App测试加载失败，改为绑定公共URL后复验通过，失败日志保留在 `tmp/interface-cleanup-20261030/entry-tests.log`。

实机：浏览器访问最初受设置关闭阻断，用户开启后可用；重启后5174连接被拒绝，使用现有受归属检查的启动函数恢复商城所需Case/Commerce/Gateway和网页，MySQL/Redis/RocketMQ沿用原卷。没有启动Agent/PG，没有模型/新订单/退款请求，不称完整服务启动通过。

登录1440×900与390×844检查通过，无水平溢出、图片缺失或三处已删文案；手机表单left20/right370，主视觉隐藏。截图 `tmp/interface-cleanup-20261030/login-desktop.png`、`login-mobile.png`。桌面切换到手机视口时普通截图有瞬时比例显示异常，改用fullPage并核对DOM实际尺寸，不将该捕获异常当成页面布局通过证据。商城入口已实机点击，后续全站页面检查随本批追加。

交易操作仍在其发生处说明当前模式，不在登录/页眉/页脚反复出现。当前工作不证明公网部署、真实支付接入或生产高可用，也不修改现有历史报告。

## 管理页面

`AdminOverview.vue`删除指标复述、排序说明、角色兼容解释和协调规则整栏，仅保留指标/队列/入口及实际读取时间；`AdminPolicies.vue`删除顶部说明栏和重复索引解释，政策原文、有效区间及版本仍保留，技术来源在展开项查看；`AdminPeople.vue`删除页头口号、账户归属说明和密码实现细节，密码长度放入输入占位；`PlatformWorkspace.vue`删除标题下重复的页面职责描述。没有删除错误、最后管理员保护、本人修改后退出或密钥保存等实际操作信息。

`pnpm --dir web test -- tests/admin-workspace.spec.ts tests/admin-people.spec.ts tests/foundation.spec.ts`：16项通过。实机admin01登录后概览/政策可进入，政策原文仍完整显示、版本来源可展开，全局标签不再出现。当前调查服务没有启动，政策索引状态显示暂不可用，保留实际状态。入口小步d9d03418已普通推送并核实远端同HEAD。

管理页批量文本脚本在Windows将四文件写为CRLF，暂存差异检查报告trailing whitespace，但该次shell未在非零退出后停止，cabfee6e已提交推送。发现后立即恢复四文件原LF并单独提交修正，不重写历史；后续提交以显式检查退出码为门禁。此处保留失败经过，功能测试16项结论不受行尾修正影响。

## 客服与结果

`SupportWorkspace.vue`移除空状态重复介绍、已转交卡片重复共享说明和列表记录复述，保留查询按钮、双方头像、消息、时间及收件人；转交对话框直接写“确认共享给商家的内容”。`SupportRefundCard.vue`删除摘要下方重复说明，编辑、提交及过期提示保持；`BuyerApplicationProgress.vue`删除成功时额外一段资金说明与金额标签中的重复模式标注，模式仅在结果头部显示一次，仍为模拟退款；`SupportOperations.vue`删除标题下固定条数/脱敏说明，实际模式、调用数字和事件保持。

`pnpm --dir web test -- tests/support-workspace.spec.ts tests/support-refund.spec.ts tests/support-operations.spec.ts tests/buyer-application-progress.spec.ts`：64项通过，包括确认共享、流式回复、恢复原请求、成功金额与模拟模式仍可见检查。没有删改原测试断言或发出新模型请求。

## 交易与审批

`App.vue`删除队列自动刷新机制解释、证据空状态的推论说明、方案后的重复执行说明及金额栏空支付信息脚注；`AdminProducts.vue`删除商品管理标题的复述；`AdminTrades.vue`删除发货按钮和确认框的重复物流实现说明，原“模拟发货/确认模拟发货”及本单发货数量保留；`FulfillmentPanel.vue`在途正文直接写商品已发出；`MerchantCaseDetail.vue`删除审批按钮下重复执行说明，确认弹窗仍说明批准后动作。

`pnpm --dir web test -- tests/app.spec.ts tests/admin-trades.spec.ts tests/buyer-orders.spec.ts tests/merchant-case-detail.spec.ts tests/foundation.spec.ts`：65项通过。页面控制条件、原请求恢复、退款授权与审批动作未改。

## 详情去重

实机历史退款结果在“退款完成”标题后仍有服务端成功消息和“仅可查看”段落，进一步在成功态只显示标题/金额/公开处理理由；其他状态的失败或阻断原因仍显示。`CustomerWorkspace.vue`把长申请范围说明收敛为金额标题中的模式，`InvestigationFindings.vue`和`InvestigationSources.vue`移除常驻的来源解释段，实际来源标签、版本不匹配和缺失记录仍明确显示。相关进度、客户工作台与调查来源四组测试通过。卡皮巴拉既有成功会话实机读回329元和公开理由，重复两段不再出现，未修改历史消息、交易或模型答复。

## 最终验收

- `pnpm --dir web test`：42文件314项全部通过；`pnpm --dir web build`：类型检查与生产构建通过。分组35/16/64/65/34项与全量存在重叠，不累计。
- 实机登录admin01、卡皮巴拉、platform分别检查商家概览/商品/政策、买家原咨询及退款结果、平台商家列表与客服运行记录；只有登录和只读页面操作，无新订单、退款、资料配置或模型请求。
- 390px手机登录与商城：DOM无水平溢出，表单宽350、搜索框宽343，搜索底111.09/主视觉顶142.09无重叠；首页12商品、图片加载通过。多标签页下浏览器级视口设置只影响当前标签，发现后用标签页限定的设备尺寸重新核对实际innerWidth=390，不沿用其他页尺寸作证明；检查后清除临时覆盖。
- 最终截图：`tmp/interface-cleanup-20261030/login-final.png`、`shop-desktop.png`、`login-mobile-final.png`、`shop-mobile-final.png`、`buyer-result.png`、`merchant-policy.png`、`platform-operations.png`。登录截图用实际页面无损PNG保存，未编辑页面内容。
- 登录页保留供用户体验。服务当前5174/8180/8181/8183运行，Agent/PG未启动；未称完整业务运行与模型调查复验通过。原四份历史未提交文件保留，本批源码和记录均分步普通推送。

本批覆盖17个Vue组件及2个共享样式文件。常驻职责说明和重复提示直接从模板移除；字段标签、店铺/商品身份、金额、状态、错误、来源和确认后果仍在对应位置显示。旧设计预览的合成标记与历史记录原文保持，不把视觉精简变成对历史数据或实际交易模式的改写。
