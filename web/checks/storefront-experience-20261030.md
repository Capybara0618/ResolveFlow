# 商城连续性与确认弹窗（2026-10-30）

## 确认弹窗重设计

用户指出原框布局生硬。共享ReviewDialog移除工作区副标签/标题分割线、统一20px标题与15px正文，遮罩改中性浅灰绿/2px模糊，框体轻阴影18px圆角；新增独立footer插槽。买家取消使用440px紧凑框，操作在底部右侧，文案“暂不取消/取消订单”，取消动作用低饱和红色，窄屏等宽。面板程序聚焦不画整框外轮廓，键盘按钮焦点仍可见。旧表单正文插槽兼容。

- 原2个订单断言依赖旧“确认取消”文字失败，改为弹窗内明确操作定位；保留取消前零请求、显式确认及取消丢响应阻止付款断言，未删安全检查。新增footer键盘循环覆盖。
- `pnpm --dir web test -- tests/review-dialog.spec.ts tests/buyer-orders.spec.ts tests/admin-people.spec.ts tests/reviewer-workspace.spec.ts`：51项通过；`pnpm --dir web build`通过。
- 复用上一批buyer01专用未付款草稿，未创建新草稿。桌面实际440px/按钮靠右；390屏宽334.67px框、两40px高按钮同排，无横溢；暂不取消/Esc关闭通过，未确认取消/付款/退款/调用模型。截图tmp/storefront-motion-20261030/dialog-desktop.png、dialog-mobile.png。
- 浏览器旧连接句柄报browser.user不可用，重置控制会话后绑定原标签成功，未要求用户重启或改权限。视口已reset。


## 商城与购物车连续性

MarketplaceWorkspace使用历史条目标识保存最多12个同账号浏览视图，商品列表快照按实际读取时间5分钟过期。保留列表页码/游标/筛选及位置，商品只保留所选规格与数量，回到商品仍重新读取当前SKU/价格/数量上限；购物车每次进入重新读取记录，再过滤恢复仍可买的勾选项。记忆只在当前账号工作区内存中，history只存不含凭据的条目标识；退出/换账号即销毁。失败读取不生成空列表快照，过期重新读；不是跨刷新持久缓存。

首次慢读取150ms后显示列表/商品/购物车结构骨架；快请求不闪提示，分页/购物车刷新保留原记录，不再插入加载文字撑高页面。商品和购物车确认页先回顶部，返回时恢复原阅读位置。购物车图片与商品名可进入详情，顶栏返回优先退出购物车确认页，再退到上个页面。原幂等请求、版本检查和未知结果禁止离开保持。

### 验证

- 关键4例先红：商城返回重复读取、规格数量重置、购物车勾选丢失、刷新插入提示；实现后通过。补充真实history往返、慢读不闪空结果、确认页返回、5分钟过期/失败不缓存。
- 最终相关 `pnpm --dir web test -- tests/marketplace.spec.ts tests/cart-workspace.spec.ts tests/buyer-navigation.spec.ts tests/app.spec.ts`：63项通过。
- `pnpm --dir web test`此前362项通过；最后追加过期/失败缓存回归后最终46文件364项通过，重叠不累计。`pnpm --dir web build`最终通过。jsdom scrollTo未实现提示保留，真实位置另验。日志tmp/storefront-red.log、storefront-tests.log、storefront-final-tests.log、storefront-build.log。
- buyer01实机：商城第2页4件→双肩包详情→橄榄绿/数量3→购物车→返回详情，规格/数量和绿色图片恢复，现价189；再返回商城，第2页4件保留，鼠标坐标操作前后scrollY均326.666656。未提交订单。
- buyer10原购物车为空，通过正式API只新增1条黑色耳机/数量1供验证；不改原已有购物车记录，不提交草稿或付款。取消勾选→点商品→返回，仍未选中、合计0；重新勾选进入只读报价确认后，顶栏返回回到购物车、勾选保留。专用购物车行保留，没有删除/清库。
- 390×844购物车单价/数量/小计均在框内，document.scrollWidth375<viewport390；商品主图宽342.67且无横溢。检查后reset视口，全部服务/购物车验收页保留。截图tmp/storefront-motion-20261030/catalog-return.png、cart-return.png、cart-mobile.png。
- 本批没有新增付款、退款、确认取消、业务消息或模型请求。骨架慢网与失败恢复通过受控回归验证，本轮未注入真实网络节流。剩余个人页、商家和管理员的复杂状态保留另按样板接入。
