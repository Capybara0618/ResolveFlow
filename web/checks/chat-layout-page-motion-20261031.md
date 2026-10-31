# 买家聊天宽度与页面切换验收

日期：2026-10-31。用户要求：修正聊天两侧空白、内容挤在中间，以及买家页面切换突然出现的问题。按整批代码后集中实机验证执行，保留此前业务数据。

## 实现

- `buyer-support.css`：取消整个消息轨道的 900px 居中限制；标题、消息、输入区共用 16–40px 自适应边距。助手单条回复最大 880px，买家消息最大 680px；申请卡仍限制阅读宽度。
- `page-motion.ts`：统一导航动效生命周期。普通导航在实时 DOM 上更新，内容真正准备好后，最多六个可见分组以 240ms、小幅位移与 35ms 错峰进入；返回采用对应方向。轮询、流式文字和表单输入不触发页面入场。
- 商品列表与详情使用原生 View Transitions 衔接选中的商品图片；等待新画面最多 64ms，慢请求交回骨架与实际内容入场。快照失败、浏览器不支持时继续导航；减少动态效果时不运行动画。
- `MarketplaceWorkspace.vue`：导航外壳稳定，内容容器不按路由整体重新挂载，保留已有订单组件、浏览记忆与表单工作区。商品分页、确认订单和返回规格页接入同一动效入口。
- `ProductGallery.vue` 标记对应商品媒体；订单、购物车、资料页标记有限入场分组。资料和咨询页显式提供首次加载状态。
- 依赖和锁文件未变，权限、写入幂等、金额及 Agent 循环未变。

## 集中自动化

| 实际命令 | 结果 |
| --- | --- |
| `pnpm --dir web test -- tests/page-motion.spec.ts tests/marketplace.spec.ts tests/support-workspace.spec.ts` | 第一轮 71 项通过 |
| `pnpm --dir web test -- tests/page-motion.spec.ts tests/marketplace.spec.ts tests/buyer-orders.spec.ts tests/cart-workspace.spec.ts tests/account-workspace.spec.ts tests/support-workspace.spec.ts` | 中间 118 项通过 |
| `pnpm --dir web test` | 最终 47 文件、392 项通过 |
| `pnpm --dir web build` | 最终 vue-tsc 与 Vite 构建通过 |
| `git diff --check -- web` | 通过 |

最后补充“标题不随晚到内容重播”检查时，第一次集中运行为391通过/1失败：jsdom没有Web Animations，测试只给子节点设置animate，漏了控制器用于能力探测的根节点。补齐同浏览器能力的测试桩后再集中运行；首次失败保存在`tmp/page-motion-heading-first-failure.log`，未删除断言。

新动效测试覆盖：快照前后提交时机、样式恢复、慢请求释放、子工作区加载、过期导航取消、减少动态效果、快照异常回退、观察器清理、共享商品匹配、实时 DOM 加载后入场，以及标题不随晚到内容重复播放。真实 DOM 尺寸由浏览器核对，不以 jsdom 证明排版。首次测试未先单独运行旧实现失败版本，不主张全批测试先红后绿。

日志：`tmp/page-motion-first-tests.log`、`tmp/page-motion-final-related.log`、`tmp/page-motion-all-final-tests.log`、`tmp/page-motion-final-build.log`。测试中的 jsdom `scrollTo` 未实现提示保留，未报测试失败。

## 真实浏览器

使用正式入口 `./start.ps1 -SkipBuild -NoBrowser` 一次恢复服务；10 项状态通过，政策索引复用。启动时发现旧前端 PID 存活但未持有 5174，入口保留旧记录并恢复可访问前端；初次浏览器访问曾 `ERR_CONNECTION_REFUSED`，服务恢复后通过。

登录 buyer01，使用已有咨询和商品，仅进行查看、导航、检索与未发送草稿检查。本批没有新增模型请求、购买、退款、审批或评价。

| 检查 | 实际结果 |
| --- | --- |
| 1920×1080 聊天 | 主区宽 1619px，消息轨道宽 1528px；消息距主区左侧约 40px，取消原 900px 轨道居中；输入区底部 1059px，小于窗口 1080px |
| 1440×900 聊天 | 主区宽 1139px，轨道约 1065px；输入区 y=769、底部 879px；打开/关闭订单资料，未发送草稿保留 |
| 1280×720 最终默认窗口 | 主区宽 979px，轨道约 912px；输入区底部 699px，小于窗口 720px |
| 390×844 | 无横向溢出，消息正常换行；沿用现有窄屏纵向页面与内部聊天滚动，输入区需向下滚动可达，本批未改为手机全屏聊天 |
| 商品图片衔接 | 实际采到 `rf-page-forward`、`rf-page-out` 和浏览器 `rf-product` 共享图片动画；最终键盘进入详情样本 ready 约 57ms、finished 约 352ms；返回搜索保留“键盘”条件，匹配回 `product-image` |
| 普通导航快速连点 | 订单→购物车→咨询，间隔约 47ms、39ms；三个实际点击目标分别命中正确链接，最终落在咨询页 |
| 慢请求 | 对商品查询响应临时追加 700ms 延迟，真实 API 响应内容不变；最终采样出现骨架，随后单个商品及真实内容入场，结束时 loading=false、无遗留动画 |
| 控制台与清理 | 最终 error/warn 空；临时 fetch 延迟、快照/点击采样均在 reload 后清除，视口 reset 到 1280×720，咨询页标签保留 |

证据位于 `tmp/page-motion-20261031/`：`chat-1920.png`、`chat-1440.png`、`chat-390.png`、`chat-final.png`、`runtime-probe.json`、`motion-final.json`、`slow-final.json`。原始采样保留了被取消的快照，不把正常取消当作全部成功快照；最终记录中的两个末尾快照包含一次取消和一次返回，进入详情的完成时间另已在现场读取确认。

## 实机发现与取舍

最初把所有导航放进原生快照，并等待数据最多 160ms。实机连续点击时，快照暂停绘制期间有点击落到 HTML 根元素，没有命中导航。缩短为 64ms、再改普通页面不等待请求及独立导航快照层，仍在约 60–100ms 的连点中复现。最终普通导航改为实时 DOM 入场，实测约 40–50ms 连点全部命中；原生快照只保留在确实有对应图片的商品转场。保留初次失败采样，未把“有动画”当作“操作流畅”。

实机 Page Animation CDP 域不受当前浏览器工具支持，改用应用内 `document.getAnimations()`、原生 View Transition ready/finished 与实际点击事件采样；只读 DOM 包装环境的 `typeof document.startViewTransition` 曾显示 undefined，随后通过开发用 Runtime 检查确认实际浏览器提供该函数。没有据包装环境结果误判浏览器不支持。

## 验证边界

本批范围是买家聊天与买家工作区导航。商家、平台原有动效未重新设计；Java/Python 无新增业务修改，未另跑其全套测试。减少动态效果和不支持原生转场的回退经过自动化，未在多种实体浏览器逐一验收。商品快照阶段仍有浏览器自身短暂捕获过程，因此没有把它扩展为所有页面的通用等待机制。

参考实现思想：[原生页面转场示例](https://github.com/bramus/view-transitions-demos)、[Motion Vue](https://github.com/motiondivision/motion-vue)、[Nuxt 转场生命周期](https://github.com/nuxt/nuxt/blob/main/packages/nuxt/src/app/plugins/view-transitions.client.ts)。本批保留当前 Vue 技术栈，未安装新动效库或迁移路由框架。
