# 现代商城代码实施与集中验收

2026-10-30，计划见 [modern-commerce-plan.md](../design/modern-commerce-plan.md)。按用户最新要求：M1至M7先代码与离线检查，M8统一启动/实机验收。本文记录证据，进度只看tasks/todo.md顶部。

## M1 基础尺度第一步

新增字体/空间/控件/容器尺寸变量，分页与弹窗开始消费公共变量，商城颜色接同一源；移除展示链额外品牌字号覆盖，固定品牌22px/500，不再因首页/商品路由切换改变粗细。原窄屏适配保留，未改领域状态或事件。

- `pnpm --dir web test -- tests/marketplace.spec.ts tests/review-dialog.spec.ts tests/buyer-orders.spec.ts tests/merchant-pagination.spec.ts`：实际匹配前三个文件48项通过；最后文件名不存在，未把它算成已运行测试。
- `pnpm --dir web build`通过，日志tmp/modern-foundation-tests.log、modern-foundation-build.log。纯样式/变量改动不增加复述CSS的测试。
- 浏览器访问恢复时原应用未运行，用户改变节奏前已执行正常start -SkipBuild -NoBrowser，最终10项状态PASS；沿用原卷和政策索引，未模型调用。用户新要求后不再分模块启动或实机验收。
- 预期稿原目录URL被Vite回退到主应用，HTTP200不能证明正确页面。明确入口为 `/design-review/modern-commerce/index.html`；跳转被用户中止，仍未截图或视觉验收。后续M8准确核对页面标题与内容，不将上次入口200作为实机证据。
- 原4无关脏文件保持。当前只有离线通过，不称M1最终视觉验收完成。


## M2 购物车与金额区第一步（仅离线）

新增OrderSummary公共金额区，购物车改商品区+单一结算栏；明确选择一家店，数量/金额/quote请求只包含该店已勾可用行。当前店铺在历史条目记忆中和勾选一起保留。确认页地址/商品为主列，金额/提交为侧列；真实quote.total_amount继续作为提交前展示权威。删除原购物车稀疏表格/重复店铺底部结算样式，单价就近移到商品信息，保留小计与数量。移除商品改共享确认框，未知请求依然持久恢复并阻止竞争操作。

- 新“单结算区只quote所选店铺”“取消移除不写入”先红后绿。
- 原双店总额同时可见断言失败，改为切换结算店铺后分别检查727/218，保留单店请求、地址、版本、原幂等键和未知恢复断言；原移除场景补显式确认，不删业务检查。
- `pnpm --dir web test -- tests/cart-workspace.spec.ts tests/marketplace.spec.ts tests/cart-pending.spec.ts`：实际匹配前两文件42项通过，第三文件不存在未计入。`pnpm --dir web build`通过；日志tmp/modern-cart-red.log、modern-cart-tests.log、modern-cart-build.log。
- 按用户节奏不启动/浏览器验收，无本步真实交易/模型；视觉与整链等M8集中验收。


## M2 商城、商品与直接确认（仅离线）

主内容1280px及导航内边距按同一基准对齐，主视觉降至284px/40px标题，分类与商品文字减轻。商品媒体与购买区同一首行，参数/配送/售后说明移到全宽下一行，单次资料请求保持；主图按窗口高度限制并contain完整呈现。数量增加/减少使用服务端SKU上限；加购反馈预留位置。直接购买确认复用OrderSummary，金额取quote.total_amount，原请求未知时允许原请求重试并禁止更换输入。删除废弃draft展示样式，替换原商品规则而非另叠新主题。

- 相关4文件50项通过（指定presentation.spec.ts未存在，不计为运行）；新增数量控件边界后marketplace27项通过。`pnpm --dir web build`通过，日志tmp/modern-catalog-tests.log、modern-catalog-final-tests.log、modern-catalog-build.log。
- 原直接提交断言只改明确的checkout-submit定位，保留未知原key/冻结输入、价格冲突、无地址禁止提交、晚响应丢弃及历史状态测试。
- 不启服务、不浏览器验收；主图是否完整、各桌面尺寸排版与手感留M8，不用静态CSS推断最终视觉通过。


## M3 订单分页与评价弹窗（仅离线）

买家订单从追加加载改上一页/下一页替换，服务端游标与页码在读取成功后提交；返回详情保留页号/筛选/游标/位置，刷新当前页，失败保留原页。订单抬头合并返回与刷新，状态与金额先于收货信息，筛选去重描边；评价按需读取放入统一弹窗，原保存/冲突/未知写入处理保持。

- 分页返回/下一页失败新预期先红后绿；原“已加载两页合并”改为“第2页单页保留”，仍检查同一模块、仅两次列表读取与scroll480。补当前页刷新不重置回归。
- 相关3文件26项通过；最终build通过，日志tmp/modern-orders-red.log、modern-orders-tests.log、modern-orders-build.log。
- 用户要求整批统一验收，本步无启动/实机或业务请求，不能称视觉已验。


## M3 物流与结果阅读层次（仅离线）

物流区域统一表面/边框、14px正文与紧凑状态，标题改“物流进度”；失败提示改“物流暂时无法读取，请重试”，仍不显示未发货事实。收货卡预留基本高度，退款结果金额使用稳定数字，结果正文按15px阅读尺度，评价区/按钮消费公共表面与控件变量。成功/处理中/未知/驳回状态和金额来源均未改变。

- 相关4文件40项通过、build通过；日志tmp/modern-results-tests.log、modern-results-build.log。失败物流测试仍同时断言错误存在和“不显示商家尚未发货”，仅替换旧冗长错误文案。
- 纯排版不新增镜像CSS测试；本步无服务/浏览器或模型调用，视觉待整批M8。


## M4 复合编辑的弹窗基础（仅离线）

地址管理内编辑需要多层弹窗，原每实例各自恢复overflow会在父层先卸载时提前解锁/残留锁，Esc还会冒泡关闭两层。新增同Document计数锁，最后一层退出才恢复背景；ReviewDialog与SupportDialog共享，Esc停止冒泡，恢复焦点不滚动。两个关键回归先红后绿，相关50项与build过，日志tmp/modern-dialog-stack-red.log、modern-dialog-stack-tests.log、modern-dialog-stack-build.log。未实机，下一步用于账户/地址编辑。


## M4 资料与地址编辑（仅离线）

地址新增/编辑、删除和修改登录账号接共享弹窗及独立操作底部，结算中的地址管理使用嵌入式管理层，不再展开撑长页面。资料表单两列、头像72px，统一40/44px控件、边框和局部反馈。普通刷新保留未保存资料；买家工作区拥有资料/地址草稿，退出页面后可继续，不保存密码。读取新版资料时不自动替换原expected version，用户明确选择最新或保留修改后才可提交；地址冲突保留输入并提供明确放弃修改/读取最新入口。

- 刷新丢草稿/地址未弹层两项先红后绿；补跨挂载草稿及新版资料显式选择回归。account/review-dialog/cart共33项通过，build通过；日志tmp/modern-account-red.log、modern-account-final-tests.log、modern-account-build.log。
- 原密码错误、版本冲突、地址选择版本和保存时关闭禁用断言保留。未启动/实机/真实账号修改，视觉和跨路由体验待M8。


## M4 账户入口与消息连续性（仅离线）

消息游标页号由当前买家工作区持有，进入咨询后返回重新读取原页，普通刷新不重置第一页；切换token清游标，未读写入失败保留消息。下拉层增加短淡入，展开页与资料页同宽。个人中心刷新不清旧订单/地址，不把读取失败当作空数据；登录关联注册/安全表单统一控件尺度，管理端资料复用嵌入形式避免双标题。

- notifications/account/marketplace共45项通过，新增消息第2页卸载返回及当前页刷新回归；build通过。日志tmp/modern-account-navigation-tests.log、modern-account-navigation-build.log。
- 不启动服务或浏览器，视觉与真实跳转待M8。


## M5 聊天阅读主区与按需资料（仅离线）

买家/商家聊天从固定三栏改为列表+主对话；订单物流/共享依据放共享阅读弹层，关闭不丢消息草稿、不重读当前咨询，商家也提供明确入口。同商品咨询显示真实末条时间及订单尾号，不造新摘要。聊天内容约束阅读宽度，字体与控件回同一基准；订单选择与转交弹层去冗余副标题、统一分区和底部。移除资料中泛泛“后续操作”指导。流式、失败恢复、退款卡出现次序及消息权限未改。

- 初次67项中5项因原固定资料区断言失败，更新为用户显式打开资料后保留原断言（共享报告、晚事件隔离、选中订单不串店），没有删除业务断言；编译发现Conversation无updated_at，改只用真实末条created_at。最终4文件67项/build通过，日志tmp/modern-support-tests.log、modern-support-final-tests.log、modern-support-build.log。
- 同步个人中心token切换清旧数据，普通刷新仍保留；避免连续性逻辑跨账号泄露旧视图。无实机/模型调用，聊天宽度与真实输出手感待M8。


## M6 商品资料与评价回复（仅离线）

商品新增/编辑与图片/店铺资料进入共享弹层，商品表单保存操作置独立footer，保存/刷新保留当前服务端分页；表格有水平边界，移除foundation多轮覆盖，统一字段/控件/商品图尺度。评价列表改单列，选中后弹层回复，关闭后再打开同评价保留未发布草稿；冲突、结果未知和原回复确认路径保持。修正上步残留空行空白。

- shopping-presentation/merchant-reviews/admin-trades22项通过；补商品管理foundation/product-pagination及回复草稿检查后，实际4文件15项通过（与前轮重叠不相加）；build通过。商品分页旧“刷新回首页”断言改“刷新当前页”并保留游标检查。日志tmp/modern-merchant-editors-tests.log、modern-merchant-editors-final-tests.log、modern-merchant-editors-build.log。
- 没有启动/实机、上传/商品发布或公开回复。布局与完整商家路径待M8。


## M6 概览、交易、审批与人员（仅离线）

概览待办合并成有分隔的轻量指标区，次级读失败保留原任务并显示错误。交易状态/金额先于地址，筛选用下划线而非整排主按钮，数字和字段缩到公共尺度；发货确认使用统一footer。审批保留原客户诉求→核查事实→决定顺序，只调整阅读/表单字号与表面，退款规则继续完整展示原文/版本/来源不改政策。人员列表与操作历史使用原服务端游标分页替换，刷新/保存留当前页，筛选重开页，失败不提交新页号。

- 4相关文件45项/build通过；补分页替换和失败原页回归后admin-people9项通过（重叠），日志tmp/modern-merchant-work-tests.log、modern-merchant-work-build.log、modern-merchant-people-final.log。
- M6代码阶段结束，未新建人员/发货/审批或实机验收。继续M7平台；实际布局和三角色完整路径留M8。


## M7 平台商家/买家正式分页（仅离线）

发现平台接口固定LIMIT200且无后续游标，不能在前端切已加载200条来代替全量搜索。Case新增按稳定商家标识/用户名排序的服务端搜索与limit+1游标，查询先筛后分页、LIKE通配符转义，原身份/角色复核保持；相应OpenAPI两侧类型/fixture与客户端同步。平台两类页面各自保存搜索和页号，创建/密码表单与启停确认使用共享弹层，刷新/操作保留当前页，失败保留旧数据而不显示空记录。

- Java独立Mockito3项通过，无Spring/数据库/服务启动；web平台4项通过，契约9项通过，build通过，日志tmp/modern-platform-java-tests.log、modern-platform-web-tests.log、modern-platform-contracts.log、modern-platform-web-build.log。初次Maven参数被PowerShell拆分、随后默认JDK17门禁拒绝，改引号参数与已锁JDK21后通过；未跳过Java版本门禁。初次定向Spotless把glob误当regex而失败；改为工具支持的正则后，仅本步3文件实际格式化通过（另1既有匹配文件缓存未改）。
- 数据库真实SQL/HTTP分页、账号操作、视觉留M8集中验证；本步不称实机通过。纠正上步人员测试记录为实际9项，非12项。


## M7 运行记录搜索分页与共享外壳（仅离线）

客服运行记录不再止于最近50条：Case用既有run_id定位真实时间锚点，按created_at/run_id双键倒序，检索店铺/运行、状态先筛后limit+1；只返回原允许的投影字段，保留空指标null和真实mock/live区分。前端每页8条，当前页刷新，列表和过程分层；正式OpenAPI/fixture/类型同步。平台、商家外壳品牌22px、导航76px及176px侧栏基准对齐。

- Java独立5项（含上步3，非相加）通过，web3文件15项通过，契约12项通过，最终build通过。日志tmp/modern-operations-java-tests.log、modern-operations-web-tests.log、modern-operations-contracts.log、modern-operations-web-build.log；定向Spotless通过。没有启动业务服务/数据库测试容器或调用模型。
- M1至M7代码已实现；接下来全前端回归与一次集中启动/真实SQL、三角色业务和视觉验收。尚未把代码通过记为实际体验通过。
