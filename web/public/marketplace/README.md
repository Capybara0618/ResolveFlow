# 商城首页视觉素材

## 页面与验证（2026-10-28）

用户审核预期图后实施：顶部合并品牌/搜索/买家入口，四列商品名称价格同排，店铺改为商铺图标＋店名。全部店铺选择器和商品店名均使用原真实店铺路由；切换范围保留搜索/分类，底部逛店宣传卡移除。买家账户菜单保留我的售后和退出，匿名私有入口仍要求登录。

实现见web/src/ui/MarketplaceWorkspace.vue、marketplace.css与App.vue；图标在ReviewIcon.vue复用已有SVG体系。修复工作台通用input样式带入的顶部margin/内边框，商城文字容器独立命名，避免影响后台product-copy。原15张商品图、商品数据、依赖锁及后端逻辑保持。

最终 `pnpm --dir web test` 35文件254项通过、`pnpm --dir web build` 通过，hero源/构建SHA256一致。进店/切店保留条件两项先失败后通过；一次新测试Element.value类型错误修正后构建通过。首轮全量251/252，原会话测试仍查找已移动的topbar退出按钮；改为验证新logout事件并保留清理会话/路由断言，新增实际菜单退出及匿名入口检查后全过。

真实API＋1280px桌面浏览器验证12商品/12图加载、四列、无横向溢出、输入框零内边框/零margin；店铺切换、本店搜索、切回全站、分类空结果和店名进店正常。演示买家登录恢复原店铺、账户菜单/退出实测通过。未新建交易/退款或调用Agent；Java/MQ/真实模型评测未重跑。本次不代表完整退款链验收。截图和详细记录留本机，不提交用户会话或原始业务日志。

## 横幅来源

`hero-v1.webp` 是2026-10-28使用内置imagegen生成的演示场景横幅，参考现有米白台灯和黑色耳机商品图。它不是商品实拍或实际使用效果证明。标题、按钮、商品价格和店铺信息均由真实HTML/API呈现，图片不包含文字。原15张商品图和它们的manifest保持不变。

原PNG 2172×724，SHA256 `517f9cb86d0b7b9317f1950705890a7dfb2ba612a08d65e1670b8a8609b51668`，保留于本机imagegen原输出。成品仅用Sharp 0.35.5编码WebP quality90/effort5，无缩放或裁剪，77,896字节，SHA256 `36bbab74a64fde54753c846385aed8aac8278871f5ccc0ab61c333a078083a90`。运行仅依赖提交的WebP，不需要Sharp。

完整生成提示词：

```text
Create a wide ecommerce homepage hero BACKGROUND photograph ONLY, NO TEXT, NO LETTERING, NO LOGO, NO UI. Landscape approximately 3:1. Match the approved ResolveFlow warm ivory/sage retail art direction. Reference images are exact existing product identity: ivory dome desk lamp and black over-ear headphones. Preserve their material, shape, colors and design. Rightmost 50 percent: lamp around x=68 percent and headphones at x=86 percent standing on a warm pale stone surface, subtle realistic shadows, gentle daylight with soft blurry foliage at far right. Left 50 percent mostly empty smooth warm off-white / very pale sage wall with faint soft foliage shadows only, LOW contrast so dark headline will be added by CSS, no objects covering text space. Product bottom aligned near image bottom, products fully in frame. Quiet refined premium editorial photograph, no extra products, no packaging, no marketing badges, no borders. Image only, all words will be rendered in live HTML.
```
