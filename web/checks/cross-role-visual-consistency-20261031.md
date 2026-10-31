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

## 真实浏览器复验（2026-10-31）

用户重启后浏览器已可访问。首次 `status.ps1` 显示基础依赖正常、五个应用进程停着；执行 `.\start.ps1 -SkipBuild -NoBrowser` 正常退出0，最终10项健康通过。原数据库与政策索引复用，未创建订单、退款、账号或新模型请求。

使用真实 buyer01、admin01、platform 登录，检查实际页面和 computed style，而非预期稿。

| 范围 | 复验结果 |
| --- | --- |
| 商家概览→交易订单→商品管理→商品评价→售后工单/详情→咨询核查→退款规则 | 默认1280×720下顶栏76px、侧栏176px、导航14px/44px、品牌22px不随页面变化；同类管理页标题26px、内容起点x208（176+32）一致。咨询保留内部会话布局，外侧导航不换主题 |
| 买家首页→商品→购物车→订单→售后列表/退款结果→咨询；个人中心/资料/地址/账号安全/消息 | 桌面商城导航76px、相同UI字体与配色；售后详情不再改变导航。结果、聊天及窄表单保留功能需要的宽度。商品参数可读，消息、资料和安全页正常展示 |
| 管理员商家/买家/客服运行记录及既有运行详情 | 标题26px、32px内容边距、同一顶栏和侧栏；运行详情正常读取已有3次模型/1次业务工具的记录，未触发新运行 |
| 390×720代表页 | 登录/注册/找回、买家资料/地址弹窗/聊天、商家售后列表/详情/咨询、管理员买家/运行/创建弹窗均无页面横向溢出；窄屏导航按原规则换行，长表格在自己的容器内横向滚动 |
| 弹层可达性 | 打开既有待审工单的“拒绝申请”弹窗并取消；底部按钮bottom610.73<720。地址弹窗bottom673<720，创建买家bottom631.59<720；均取消，未提交决定或保存 |
| 1024与1440补充 | 商家1024实际边距24px；1440实际几何无横溢、顶栏76/侧栏176。管理员1440×900完成实际截图，内容边距32px；以各标签实际innerWidth为准 |
| 控制台 | 三个角色warn/error日志均为空；证据目录console.json |

### 复验中补齐的两类差异

1. 概览/规则的次级按钮实测42px、售后查询46px，订单40px；原来只共享了min-height，局部padding仍在撑高。统一主/次级按钮padding为8px 16px，并去掉售后查询的12px局部padding，最终概览及售后查询均40px。44px的业务主操作与弹窗专用操作保留自己的尺寸。
2. 展开详细材料、打开审批弹窗时，基础workbench标签/边框、AftercareProduct规格/金额与MerchantDecisionForm预览仍残留旧蓝色。修改原始声明接共享token，保留错误、拒绝警告、核验结论等语义色。最终拒绝理由rgb(105,118,110)，输入边框rgb(223,229,220)，产品文字回到相同色系。

这次收尾仅5个核心样式/组件文件：interface.css、aftercare.css、workbench.css、AftercareProduct.vue、MerchantDecisionForm.vue；不改变业务模板、授权或请求时序。

### 本次实际命令与证据

- `pnpm --dir web test -- tests/foundation.spec.ts tests/merchant-case-detail.spec.ts tests/merchant-decision-form.spec.ts tests/merchant-review.spec.ts tests/buyer-application-progress.spec.ts`：实际匹配3文件39项通过；其中merchant-decision-form.spec.ts与merchant-review.spec.ts不存在，不把两者当已运行测试。
- 补跑实际存在的 `pnpm --dir web test -- tests/aftercare-products.spec.ts tests/review-dialog.spec.ts tests/review-preview.spec.ts`：3文件13项通过；本次共52项，不与前批403项叠加。
- `pnpm --dir web build`：vue-tsc与Vite通过。日志tmp/visual-consistency-acceptance-{tests,components,build}.log。
- 最终改动差异/换行审查及`git diff --check -- web`通过。全量403项为本报告前段代码批证据，未在这次纯样式收尾后重复宣称重跑。

截图与布局采样位于忽略目录 `tmp/visual-consistency-20261031/`：

- merchant-aftercare-1280-final.png、buyer-support-1280-final.png、platform-runs-1440-final.png：最终桌面截图。
- merchant-review-dialog-390-final.png、buyer-address-dialog-390.png、platform-create-390.png：实际窄屏弹窗。
- buyer-support-390.png、buyer-composer-390.png、merchant-support-390.png、merchant-aftercare-390.png、login-390.png：代表性窄屏。
- layout-samples.json：逐页实际尺寸、字体、颜色、边距；console.json：控制台检查。

浏览器截图工具在单独CDP改宽高后曾出现底部或右侧画面重复，merchant-aftercare-1440-final.png是工具采样异常，不作为页面视觉证据；早期merchant-dialog-390.png实际是内联材料区，不能当审批弹窗。最终通过原生管理员1440截图、1280商家截图及390×720直接捕获区分工具问题与页面布局。原错误截图保留，不据文件名推定尺寸。最初旧错误页reload/goto受到工具data URL限制，新建正常HTTP标签后恢复。

本轮三端视觉一致性复验通过；仅使用已有记录检查界面，没有再次验收模型质量、实际审批执行或资金闭环。临时视口已清理，仍残留尺寸的管理员临时标签已关闭；保留默认1280的买家咨询与商家售后标签、应用服务，原四个历史脏文件保持。
