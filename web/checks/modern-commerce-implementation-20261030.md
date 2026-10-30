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
