# 三端视觉一致性排查与修正

日期：2026-10-31。用户体验商家售后工单时发现与其他模块不同，要求检查买家、商家和管理员并一并修正。此批聚焦跨页面样式边界与同类控件规范，沿用已认可的米白/深绿、界面字体和局部阅读字体。

## 排查与实现

| 范围 | 确认的问题 | 本批处理 |
| --- | --- | --- |
| 商家售后工单列表/详情 | App 根节点按当前页面挂 `merchant-review-workbench`；专属样式重新定义顶栏、侧栏、品牌、全局字体和按钮。`aftercare-workbench` 还对所有商家模块的大量元素强制 16px | 移除根主题开关与宽泛字号规则，售后样式移至当前内容 `main.merchant-review-page` / `merchant-aftercare-page`；旧主题不再作用于导航、顶栏与其他模块 |
| 商家咨询核查 | `support-shell` 针对咨询页重新定义侧栏列宽、导航字号/间距，响应式断点也不同 | 删除页面专属外壳与对应 CSS，继续使用统一 176px 工作台侧栏和相同窄屏换行；内部会话列表/消息区保留自己的布局 |
| 买家商城/咨询/售后详情 | 遗留展示链类按页面切换，咨询样式存在商城导航高度/链接覆盖；售后详情通过 `:has` 修改导航字体 | 删除过时展示链外壳开关与导航覆盖；界面/阅读字体均取共享 token，售后结果的局部阅读布局保留 |
| 商家概览、订单、商品、评价、人员及管理员管理页 | 内容边距分散为 22/24/28/30/32px，概览标题 24px、管理页 26px；评价区额外 margin/max-width；通用表格按钮与其他次级按钮颜色不同 | 新增共享工作区边距 token：默认32px、≤1100为24px、≤650为16px；标题统一26px，次级操作统一40px/14px/白底，评价页面与相邻模块对齐 |
| 买家售后列表/申请 | 遗留蓝色正文/表单/信息底色，广泛16px辅助文字，标题与其他买家管理页不同 | 使用共享文字、边框、底色、绿色强调；正文15px、标签/次级操作14px、输入15px，标题26px；保留金额、状态、表单、结果的业务布局 |
| 商家规则/人员、咨询与审批材料 | 原蓝色时期的颜色继续散落在规则版本、说明、检索/来源、表格、选中背景 | 修改原有声明接共享 ink/muted/line/subtle/accent token，保留错误、警告、评价星级等有语义的状态色 |
| 登录注册/恢复与消息中心 | 同类表面和按钮使用独立近似色 | 对齐共享表面、边框、文字与强调色；消息浮层和独立账号页面保留对应功能的宽度 |

本批没有把所有页面改成同一种布局。商品主视觉、聊天阅读区、收货地址表单、工单审批区与运行记录各自的信息结构仍保留；统一的是外框、字体来源、同类标题、控件、间距与颜色。

## 代码覆盖清单

- 买家：商城/搜索/店铺/商品、购物车、订单、个人中心、资料/地址、消息、账号安全、咨询、售后列表/申请/详情。无问题的既有组件不为凑覆盖修改；商品图、金额、聊天阅读字体保持。
- 商家：概览、交易列表/详情、商品及资料编辑、评价、售后列表/详情/审批弹层、咨询与材料、规则，兼容人员管理。
- 管理员：商家、买家、运行列表/详情与创建/维护弹层，共享导航及基础管理样式。
- 基础：`tokens.css`、`interface.css`、`display-typography.css`；业务页面不再换整页主题或跨边界改主导航。

## 实际验证

| 命令/检查 | 结果 |
| --- | --- |
| `pnpm --dir web test -- tests/foundation.spec.ts`（修改前增强现有回归） | 先失败：进入售后工单后 App 根 classes 多出 `merchant-review-workbench`，证明切页更换全局主题 |
| `pnpm --dir web test -- tests/foundation.spec.ts tests/merchant-case-detail.spec.ts tests/merchant-reviews.spec.ts tests/app.spec.ts` | 主题收拢后 51 项通过 |
| `pnpm --dir web test -- tests/foundation.spec.ts tests/marketplace.spec.ts tests/customer-workspace.spec.ts tests/buyer-application-progress.spec.ts` | 最后相关 60 项通过 |
| `pnpm --dir web test` | 最终48文件、403项通过（增强原测试，不叠加历史计数） |
| `pnpm --dir web build` | 最终 vue-tsc + Vite 通过 |
| `git diff --check -- web` | 通过 |
| 源码搜索过时跨页样式标识 | `merchant-review-workbench`、`aftercare-workbench`、`support-shell`、`display-chain-marketplace` 与售后 `marketplace:has(...)` 外框覆盖在生产源码中已移除 |

增强回归同时确认商家概览→评价→售后→咨询保持 App classes 与同一个侧栏节点，售后专属类仅在内容 main，咨询不再挂独立外壳。旧业务回归继续覆盖角色隔离、表单冲突与保存、订单/退款和草稿。

日志：`tmp/visual-consistency-first-failure.log`、`tmp/visual-consistency-shell-tests.log`、`tmp/visual-consistency-final-related.log`、`tmp/visual-consistency-final-tests.log`、`tmp/visual-consistency-final-build.log`。

第一轮类型检查发现新增断言误用 `get(...).exists()`，测试库类型不允许对 get 结果调用 exists；改为 find 后通过，原失败保存在 `tmp/visual-consistency-first-build.log`。没有删除业务断言。jsdom 原有 scrollTo 未实现提示保留。

## 尚未完成的实机验收

此批请求浏览器库存时明确返回 `Local browser use is disabled in Work settings`，已请求开启；当前无法进入真实页面读取 computed style 或保存本批新截图。此前截图仅证明旧版本，不能作为此批视觉通过证据。

开启后应集中核对：商家概览/订单/商品/评价/售后/咨询/规则切换前后顶部与侧栏几何及字体不变；买家商城/订单/消息/个人资料/售后/咨询导航保持同一规范；管理员三模块标题、边距、次级按钮一致；1280/1440/390的换行、工单详情与审批弹层操作区可达。保留各角色现有记录，只读切换与弹层打开/取消即可，不创建新订单或模型调用。

本批代码与自动化完成，视觉验收待浏览器访问恢复。未重启服务、未改 Java/Python、未新增模型/购买/退款/账号写入，四个原历史脏文件不在提交范围。
