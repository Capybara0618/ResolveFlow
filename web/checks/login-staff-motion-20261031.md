# 登录、商家与管理员体验统一验收

日期：2026-10-31。承接买家导航动效后，用户要求登录页、商家端和平台管理员端也采用同一套体验。范围是入场、实际加载衔接、内部页面切换及读取期间的导航响应；业务操作仍由原页面和服务负责。

## 实现与取舍

- 新增 `usePageEntrance.ts`，以页面身份、DOM 根节点和显式 `data-page-key` 感知切换，在 Vue 更新后接入已有 `page-motion` 的实时 DOM 入场。未改变业务事件处理的同步顺序，不重新挂载页面来制造动画。
- 登录首屏左侧场景自然进入，表单标题、输入、按钮以 240ms / 35ms 错峰呈现。注册、找回与返回登录只更新表单区，左侧保持同一 DOM 节点。
- 商家概览、交易列表与详情、商品与图片管理、评价、售后列表与详情、咨询、规则、人员管理接入加载状态和内容分组。分页/详情通过显式页面身份进入；轮询、消息增量、刷新和输入不重播整页动效。
- 管理员商家/买家/运行记录页面复用同一入口；运行详情独立进入，列表保持稳定。共用 `PageLoading.vue`，慢于 150ms 的空列表才显示骨架；有旧内容时刷新保留原列表。
- `page-motion` 增加根节点本身的加载识别和跨控制器原生状态所有权，避免商家/登录的实时动效清掉另一个工作区的商品快照状态。减少动态效果仍沿用原机制。
- 商品只读加载不再向父工作台报告为阻塞业务写入；平台区分读取与保存，允许读取期间切换页面，并以请求代次、目标页面拒绝迟到的结果/错误。保存期间导航仍受保护。
- 未新增依赖、路由框架或服务；不改 Agent、Java 权限、审批与金额约束。

## 自动化

| 实际命令 | 结果 |
| --- | --- |
| `pnpm --dir web test -- tests/page-motion.spec.ts tests/foundation.spec.ts tests/app.spec.ts tests/admin-workspace.spec.ts tests/admin-trades.spec.ts tests/merchant-reviews.spec.ts tests/support-operations.spec.ts` | 第一轮 63 项通过 |
| `pnpm --dir web test -- tests/page-entrance.spec.ts tests/page-motion.spec.ts tests/foundation.spec.ts` | 中间 24 项通过 |
| `pnpm --dir web test` | 最终 48 文件、403 项通过 |
| `pnpm --dir web build` | 最终 vue-tsc 与 Vite 构建通过 |
| `git diff --check -- web` | 通过 |

新增检查覆盖：根节点加载后才出现数据、标题不重播、输入/刷新不重复入场、切页取消旧等待、内部页身份与草稿保持、减少动态效果/卸载清理、骨架延迟与刷新保留、跨控制器状态隔离、平台迟到错误隔离、商品只读不锁导航、保存期间继续保护导航。

首次新增类型检查发现测试夹具向 `PlatformBuyer` 填入不存在的 `buyer_id`，删除错误测试字段后通过；日志保留 `tmp/staff-motion-code-build.log`，没有更改生产契约或降低类型检查。最终日志为 `tmp/staff-motion-final-tests.log`、`tmp/staff-motion-final-build.log`。jsdom 的既有 scrollTo 未实现提示保留。

## 集中实机

使用此前已启动的 5174 页面和既有数据，未反复重启服务。实际登录 admin01、platform；用户原买家页保留。没有新增账号、商家、订单、发货、退款、审批、评价回复或模型请求。

| 场景 | 证据与结果 |
| --- | --- |
| 登录→注册→登录→找回→登录 | 实际采到 240ms 表单入场，5 个登录区域延迟为 0/35/70/105/140ms；左侧 DOM identity 保持；仅查看表单，没有注册或重设密码 |
| 商家概览 | 标题先入场，指标与待办在数据就绪后出现；交易、商品、评价、工单、咨询与规则均实际进入 |
| 商品慢读 | 真实响应临时追加 700ms 延迟，约 191ms 起采到骨架，最终 8 行、loading=false；采到 header 与 table 的独立 240ms 入场 |
| 读取中导航 | 商品请求未返回时切往交易订单，正确停留交易页；迟到商品结果未覆盖当前页。编辑商品弹窗可开关，未提交保存 |
| 商家详情与咨询 | 查看已完成工单、订单详情，未触发业务动作；咨询输入未发送草稿后刷新，草稿保留且新增整页入场次数为 0 |
| 平台买家慢读 | 临时追加 700ms 延迟，骨架后显示 8 行；表头和表格分别进入。等待期间切往运行记录，最终页面正确 |
| 运行列表/详情 | 实际查看既有 run，采到 header、operations-list、operations-detail 分别入场；未触发新的运行 |
| 表单与窄屏 | 390×844 登录表单 bottom≈682px；创建买家表单底部操作栏 bottom≈716px，均可见；仅填写一个临时账号草稿并取消，没有输入新密码或提交创建 |
| 尺寸与清理 | 登录/商家/管理员 1280，管理员运行页 1440，登录/商家/管理员 390 均检查实际 innerWidth 与根 scrollWidth，无横向溢出；最终 error/warn 空，临时 fetch/animate/点击采样已随刷新清除 |

证据目录 `tmp/staff-motion-20261031/`：`login-final-1280.png`、`login-390.png`、`merchant-final-1280.png`、`merchant-390-verified.png`、`merchant-support-1280.png`、`merchant-case-1280.png`、`platform-run-1440.png`、`platform-form-390.png`、`platform-final-1280.png`（该旧文件实为390，不作为1280证据）、`merchant-probe.json`、`platform-probe.json`。

视口检查曾发现浏览器能力只改变所选标签，商家实际仍为 1280；已读取各标签实际尺寸并对商家单独核对 390，使用 verified 文件，不把初始误命名的截图当窄屏证据。临时平台窄屏标签关闭，另建默认 1280 管理员页保留；商家指标覆盖已清除，最终商家与管理员均回到默认窗口。

## 最后核对补充

从未完成的列表读取直接切到运行记录时，运行页不会发起另一轮平台列表读取，原operation代次此前未更新；旧读取401会错误触发expired。新增回归先失败（`tmp/staff-motion-departed-first.log`），switchPage统一使原读取代次失效并释放只读busy，最终403项/类型build通过。该最终小修通过自动化；再次浏览器检查时工具明确返回“本地浏览器访问已关闭”，因此未把此前实机结果冒充这个小修的再次实机结果。既有三端实机证据保持。

## 边界

本批验证的是三端进入、加载、只读切换、表单打开/取消和交互连续性；未重做 Java/Python 全套或真实模型/退款闭环。人员管理沿既有兼容商家入口完成代码和自动化，当前单商家账号隐藏人员入口，未用它声称新的人员管理实机通过。已有表单保护与错误恢复继续保留，不以动效替代业务状态。
