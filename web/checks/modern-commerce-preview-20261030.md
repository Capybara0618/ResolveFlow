# 现代商城体验计划与 M0 样板

2026-10-30。用户要求先详细计划，再按模块依次执行。计划见 [modern-commerce-plan.md](../design/modern-commerce-plan.md)，实际执行状态只写 tasks/todo.md 顶部。

## 本步交付

- 计划定义 M0 样板、M1 统一基础、M2 商城购买、M3 订单物流评价售后、M4 账户、M5 助手、M6 商家、M7 平台管理员、M8 全链验收；各模块有源码位置、路径与完成条件。
- 独立预期稿：`http://127.0.0.1:5174/design-review/modern-commerce/`，源码 `web/public/design-review/modern-commerce/{index.html,style.css,app.js}`。顶部审查工具独立于产品页面，明确预期稿属性。
- 四页连通：搜索/分类/店铺→商品规格换图与数量→加入购物车→按店铺勾选/结算→收货地址修改→确认结果→返回。购物车改为商品区加独立结算区，金额只统计选中店铺，不将跨店商品一次提交。
- 审查工具可切换正常、加载、空结果、失败；预期稿内可体验重试与明确移除确认。现有商品图片与字体复用，不新增素材收费。
- 保留米色/深绿方向，标题/正文/操作分层；返回放在固定导航，不另占商品图片上方一行。桌面主图按窗口高度约束，为缩略图保留空间，是否达到目标仍须浏览器实看。
- 仅在预期稿内存中操作，未接交易、账号或模型 API。地址/评价/提交结果是预期稿状态，不是实际购买、已购评价或正式能力验收。刷新重置样板。

## 实际检查

1. `node --check web/public/design-review/modern-commerce/app.js`：通过。
2. `node tmp/modern-commerce-preview-check.mjs`：通过。基于 jsdom 的独立逻辑检查，不是实机浏览器：四页连通、银色换图/数量3、按店铺勾选后1047.00、返回勾选保留、地址弹窗焦点与Esc、点击移除先不删除、提交预期状态、加载/空/失败切换、搜索转义、无 fetch/XHR API 调用、图片/字体资源路径。原始检查脚本在忽略 tmp，未增加依赖。
3. `pnpm --dir web build`：通过；日志 tmp/modern-commerce-preview-build.log。独立静态稿没有修改生产 Vue/Java/Agent，未重复跑前批364项后宣称新逻辑覆盖。
4. 预期稿 HTML/CSS/JS 的 HTTP 入口均200，分别 text/html、text/css、text/javascript。只检查静态资源可访问性，不代替浏览器运行验证。
5. `git diff --check`、计划链接和关键 Vue 模块路径检查通过。

## 未运行与下一步

- 浏览器工具返回“Local browser use is disabled in Work settings”。本步没有实机截图、布局尺寸、溢出、字体加载或手感结论；不复用旧截图当新版图，也不绕过设置使用另一自动化浏览器。
- 下一步先对四页预期稿进行桌面实看与用户集中校准；方向明确后，按计划 M1 起逐模块落入正式界面。
- 原四个无关脏文件保持。无新增真实订单、地址、评价、退款、业务消息或模型请求；服务与数据保留。
