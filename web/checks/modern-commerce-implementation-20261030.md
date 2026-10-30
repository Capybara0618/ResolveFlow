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
