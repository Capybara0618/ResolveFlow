# 全站文案精简与首页调整（2026-10-30）

用户要求移除无助于操作的辅助说明，改善登录首页和商城首页。按界面小步处理，不改变身份、金额、授权、订单或退款逻辑。

## 入口与首页

`App.vue`移除全局演示标签、登录副说明、身份范围提示和侧栏口号；保留字段标签、登录/注册/找回和商城入口。登录页改为双栏：主标题与现有生活场景图、独立登录表单，390px下仅显示表单。`interface.css`统一间距、48px输入和按钮，`MarketplaceWorkspace.vue`删除全站商城说明页脚，`marketplace.css`调整首页主视觉、标题字重和明确的浏览按钮。

命令：`pnpm --dir web test -- tests/app.spec.ts tests/marketplace.spec.ts`，最终35项通过；`pnpm --dir web build`类型检查/生产构建通过。首次静态img地址在Windows Vitest转换成file:///marketplace路径导致App测试加载失败，改为绑定公共URL后复验通过，失败日志保留在 `tmp/interface-cleanup-20261030/entry-tests.log`。

实机：浏览器访问最初受设置关闭阻断，用户开启后可用；重启后5174连接被拒绝，使用现有受归属检查的启动函数恢复商城所需Case/Commerce/Gateway和网页，MySQL/Redis/RocketMQ沿用原卷。没有启动Agent/PG，没有模型/新订单/退款请求，不称完整服务启动通过。

登录1440×900与390×844检查通过，无水平溢出、图片缺失或三处已删文案；手机表单left20/right370，主视觉隐藏。截图 `tmp/interface-cleanup-20261030/login-desktop.png`、`login-mobile.png`。桌面切换到手机视口时普通截图有瞬时比例显示异常，改用fullPage并核对DOM实际尺寸，不将该捕获异常当成页面布局通过证据。商城入口已实机点击，后续全站页面检查随本批追加。

交易操作仍在其发生处说明当前模式，不在登录/页眉/页脚反复出现。当前工作不证明公网部署、真实支付接入或生产高可用，也不修改现有历史报告。
