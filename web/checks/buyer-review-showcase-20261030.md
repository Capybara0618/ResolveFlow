# 商品评价展示与拍摄准备验收（2026-10-30）

## 问题与改动

原商品详情已经挂载ProductReviews并调用正式接口，P-1001/P-2001/P-3001均返回0条，因此只有空态，且评价位于图集/参数之后，首屏无入口。此次复用同一评价请求的服务端summary，在价格下显示评分/数量，点击平滑定位评价区；切换商品清空摘要，忽略迟到响应。不新增第二次摘要请求，不写死评分或评价。评分分布改紧凑间距和统一绿色meter；保留公开匿名“已购用户”规则。

## 展示资料

fixtures/showcase/v1/reviews.json：P-1001三条展示样例，5/4/5星，黑/银/黑，两条商家回复。已有评价/账号记录全部保留。通过正式注册/登录/地址/下单/模拟付款/商家发货API，已有受控物流模拟器追加DELIVERED，然后本人资格接口、评价写入、所属商家回复API；未SQL插入评价，未改原退款订单物流。

卡皮巴拉账号仅增加一笔正常已签收订单，其余两笔归专用背景账号；当前卡皮巴拉订单列表恰为一笔已完成、一笔已全部退款。采购合计100700分（32900+34900+32900）为系统模拟付款，无真实扣款。公开接口返回count=3/average=4.7/stars=[2,1,0,0,0]，三条正文/两条回复与fixture逐字段一致。

| 样例 | 订单 | 订单行 | 评价ID |
| --- | --- | --- | --- |
| capybara | 56d247c8-62ba-465b-bb78-3654d211ad1c | SHOP-5f737860-95ab-44d9-8f1e-1d0120fd2023 | 1 |
| silver | 13ae9663-52fe-4f34-add8-4853422c905b | SHOP-c3886bd6-127b-490e-8bc3-d5db87da6d34 | 2 |
| black | 57cb2e52-f7dd-4a7a-80aa-418ad35ea335 | SHOP-61e7d2c4-50d2-45e7-8fa5-3579293fd3ce | 3 |

请求冻结幂等键、凭据和响应仅存在忽略目录tmp/buyer-reviews-20261030/journal.json；准备脚本同目录prepare.py，重新运行读取原结果，不新增订单/重复评价。脚本与凭据不提交，另一环境可按fixtures说明走正常界面准备。

## 实际验证

- 首屏摘要/点击滚动/不额外查询/切换商品清空，以及子组件摘要事件/迟到响应3处新增断言先红；修正后 `pnpm --dir web test -- tests/marketplace.spec.ts tests/product-reviews.spec.ts tests/product-review-editor.spec.ts tests/merchant-reviews.spec.ts`：4文件31项通过。
- `pnpm --dir web build`：类型检查和构建通过；`git diff --check`通过。没有改后端评价资格/缓存/数据契约，所以不重建Commerce、不重复原后端全套。
- 实机卡皮巴拉1280×720：首屏评分和3条入口；点击后定位评价区，评分、分布、原文、商家回复可见。390×844：相同3条/2回复，无横向溢出；临时视口已reset。
- 买家“我的订单→已完成→查看订单→评价商品”：当前本人5星正文和商家回复正确；“修改评价→保存评价”原文重复提交，显示“评价已保存。”，没有增加评价数。
- 商家admin01“商品评价→银色4星”：三条同源，已保存回复正确；“发布回复”原文重复保存显示“回复已保存。”，未改正文。验收标签页已关闭。
- 再次运行prepare.py，仍为同3个review_id、count3、4.7、2回复；跨公开/本人/商家三个入口一致。原始输出preparation.log/verify.log/public.json均忽略，不提交凭据。
- 截图：tmp/buyer-reviews-20261030/product-rating-entry.png、reviews-desktop.png、reviews-replies.png、reviews-mobile.png、buyer-review-editor.png、merchant-review.png。

## 拍摄与边界

README.recording-guide.md把商品首屏→点击评分→展示买家评价和商家回复设为主视频必拍段（约6秒），增加可选的独立签收订单编辑/回复补镜，明确与丢件退款主线分开。素材是功能样例，不代表商用真实客户证言，指标来自保存的样例记录。

未自动录制/剪辑新视频，用户继续自行拍摄。Agent保持关闭，无模型请求/新增退款；本轮客服停机修复见buyer-assistant-offline-20261030.md。只保证本批已列行为，不把当前评价验证称为全项目无缺陷或真实模型复验；原4无关脏文件保留。
