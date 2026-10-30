# 商城连续性与确认弹窗（2026-10-30）

## 确认弹窗重设计

用户指出原框布局生硬。共享ReviewDialog移除工作区副标签/标题分割线、统一20px标题与15px正文，遮罩改中性浅灰绿/2px模糊，框体轻阴影18px圆角；新增独立footer插槽。买家取消使用440px紧凑框，操作在底部右侧，文案“暂不取消/取消订单”，取消动作用低饱和红色，窄屏等宽。面板程序聚焦不画整框外轮廓，键盘按钮焦点仍可见。旧表单正文插槽兼容。

- 原2个订单断言依赖旧“确认取消”文字失败，改为弹窗内明确操作定位；保留取消前零请求、显式确认及取消丢响应阻止付款断言，未删安全检查。新增footer键盘循环覆盖。
- `pnpm --dir web test -- tests/review-dialog.spec.ts tests/buyer-orders.spec.ts tests/admin-people.spec.ts tests/reviewer-workspace.spec.ts`：51项通过；`pnpm --dir web build`通过。
- 复用上一批buyer01专用未付款草稿，未创建新草稿。桌面实际440px/按钮靠右；390屏宽334.67px框、两40px高按钮同排，无横溢；暂不取消/Esc关闭通过，未确认取消/付款/退款/调用模型。截图tmp/storefront-motion-20261030/dialog-desktop.png、dialog-mobile.png。
- 浏览器旧连接句柄报browser.user不可用，重置控制会话后绑定原标签成功，未要求用户重启或改权限。视口已reset。
