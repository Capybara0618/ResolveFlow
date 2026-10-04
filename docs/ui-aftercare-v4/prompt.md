# 内置image_gen生成提示词（2026-10-04）

品牌为现有ResolveFlow，图片是新设计候选，非修改旧截图；不使用参考图或创建额外模型脚本。

```text
Use case: ui-mockup
Asset type: a high fidelity desktop web app expected-design image, not an implemented screenshot.
Create ONE refined, extremely readable simplified merchant after-sales case-detail screen for ResolveFlow. Chinese interface, landscape 1600x1000 proportions, front-facing flat browser content (no browser chrome, device, perspective). Clean blue and white aesthetic matching a restrained online shopping site, pale slate canvas, white cards, subtle borders, very gentle shadows. It must look like a polished real web product, not a developer dashboard.

Critical typography: at a 1600px-wide canvas, every visible word including navigation, labels, status, buttons, auxiliary sentences and link text is at least 20px, main body 22px, card headings 26px, main title 34px, money 36px. Generous line spacing. NO tiny text ANYWHERE. Use simplified Chinese carefully and render only the specified text. No microcopy, disclaimers, footer, watermarks, timestamps, IDs, source paths, JSON, version numbers, tool names, confidence, long tables, marketing filler, or nested disclosure clutter.

Composition: slim 76px white top header with blue four-square logo + ResolveFlow on left, readable small blue-outline badge "界面预期图", merchant "松间数码" on far right. Light left sidebar 180px wide, ONLY five large labels and minimal consistent outline icons: "商家概览", "交易订单", "商品管理", "售后工单" (selected blue pill), "售后政策". Main content beginning 215px from left has one header row: blue back link "← 返回工单列表", large "退款申请", readable amber pill "待处理". Below, two columns with 28px gap: left around 835px wide, right around 335px wide. Everything fits one desktop viewport without dense packing, with generous breathing space.

Left column three stacked cards:
1) White product/order card heading "商品与订单". Large approximately 110px tasteful navy over-ear headphones product illustration on a pale blue-gray square, product title "无线降噪耳机", specification "黑色 · 数量 1", "实付 ¥329.00". A clearly readable neutral badge "未发货" and readable link "查看订单" on the opposite side. No SKU or order IDs.
2) White customer request card heading "客户申请". Main black body text "暂时不需要了，商品还未发货，希望申请退款。" Under it a simple readable muted line "客户未提交额外材料". Do not invent media uploads or evidence thumbnails.
3) Pale powder blue Agent card heading "Agent 建议". Strong blue recommendation with a small sparkle icon "建议批准退款". Below three short generously spaced readable lines: "订单已付款，商品尚未发货", "符合本店未发货退款政策", "未发现已退款记录". These represent an illustrative expected case, not fabricated forensic certainty. At its bottom ONLY ONE clearly readable blue link "查看详细依据 →". No other expandable links or scattered extra text. No duplicate paragraphs of model reasoning.

Right column ONE white card only, heading "退款处理", "申请退款", prominently "¥329.00". Three vertically stacked wide 54px tall large buttons: strong royal-blue primary with white text "批准退款"; pale blue outlined secondary "要求补充说明"; restrained red outlined "拒绝申请". Below ONE necessary readable 20px sentence "批准后执行模拟退款". Do not claim the refund is already successful. No authorization jargon, technical status panels, or decorative extra cards.

Aim for immediate comprehension in five seconds: product, what buyer asks, what Agent recommends, what merchant can do. Keep the layout compact enough to see ALL four business areas and all three buttons at once, but typography must stay genuinely large. Do not add any text not explicitly specified.
```
