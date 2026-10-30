# 统一交互体验样板（2026-10-30）

## 第一步：订单切换连续性

订单列表/详情原按ordersRoute作为key重建组件，BuyerOrders.route又清空列表，返回丢已加载页与阅读位置。移除路由级重挂载，显式routeKey同步；本账号组件内最多8个列表视图、5分钟内存快照保存已加载记录/游标/滚动位置，不写localStorage或跨账号复用。详情与售后资格仍读取权威接口，付款/取消写入成功清除列表快照，未知写入仍阻止离开。

新路由只重建内容区，侧栏/导航保持；内容160ms轻淡入4px，慢读取150ms后显示结构骨架，快返回不闪加载提示。减少动态效果时关闭动画。详情始终清除上个订单内容，迟到结果受原generation约束。

- 新返回/骨架回归先红：组件重建、无慢读骨架。实现后原用Vue测试包装器vm对象引用比较产生同uid但代理不同的失败，改为真实根DOM身份，仍要求同实例、两页记录保留、原筛选/滚动恢复及只请求两次列表。
- `pnpm --dir web test -- tests/buyer-orders.spec.ts tests/buyer-navigation.spec.ts tests/marketplace.spec.ts`：39项通过。
- 首次build因测试query参数可选而类型报错，修为query?.cursor；最终 `pnpm --dir web build`通过。
- 本步尚未实机验收，继续统一弹窗与操作反馈后集中验收。无新业务操作/模型请求，旧4个无关脏文件保持。
