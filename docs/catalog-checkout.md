# 商品目录与直接购买

2026-10-03，第二批M01–M04/M06的正式协议。复用三Java服务：Commerce拥有公开店铺、商品、SKU和未支付草稿；Case提供公共目录及受持久身份校验的买家入口，Gateway仍只转发Case。支付发布属于第三批；本批不产生已支付订单、账本、退款槽或物流。

## 公开目录

`GET /api/v1/shop/products`接受query（最多80字符）、category（electronics/home）、store_id、after（商品ID）、limit（1–48，默认24）。商品ID升序分页，返回items和next_after；搜索按字面匹配商品名，不解释SQL通配符。只返回店铺/商品/SKU均启用的商品，价格为可售规格最低整数分。`GET /shop/products/{product_id}`返回公开说明、稳定插画asset_key及可售规格；下架和未知均404。`GET /shop/stores`和`GET /shop/stores/{store_id}`返回公开商店资料。目录无需登录，不返回买家、订单、政策、内部版本hash或销量/库存承诺。

店铺公开品牌为松间数码/拾光家居，分别对应M-1001/M-1002。公开品牌独立于已有身份商家名，不改历史身份、政策或订单。种子仅为合成演示商品，SKU允许1–10件，无库存系统；单价、上下架和规格版本均是服务端事实。

## 报价与草稿

`POST /api/v1/shop/quote`正文仅sku_id/quantity，公开报价包含商品、店铺、规格、单价、数量上限、sku_version和total_amount/currency。不是价格保留；提交时必须重新核对。

`POST /api/v1/shop/drafts`需要当前平台买家身份、Idempotency-Key（1–128字母/数字/连字符/下划线）；正文仅sku_id/quantity/expected_sku_version。旧绑定客户和工作人员403；缺身份401。Case只尝试本人可信复合映射，Commerce核对实际SKU店铺，不匹配404且不创建；下架后仍可重放原草稿，无启用映射404，不能接受前端merchant/customer/buyer或金额。Commerce内部调用要求独立commerce:checkout且部署主体case-service；Agent读凭证不获得它。

Commerce追加checkout_draft，固化merchant/customer、商品/SKU/规格名称、单价、数量、金额、SKU版本、请求键及UTC时间。只有WAITING_PAYMENT，15分钟到期后读取投影为EXPIRED；无paid_at、订单行或退款槽。创建事务锁定实际SKU及商品/店铺，核验启用/数量/版本。旧版本409 PRICE_CHANGED，下架404，非法数量400。金额使用整数乘法、上限和数据库CHECK。

幂等范围为(merchant,customer,key)，前端新购买生成全新UUID，不跨店复用键；同键相同sku/quantity/expected_version重放同草稿，即使之后价格变化/下架/到期也不重新生成；同键不同请求409 IDEMPOTENCY_CONFLICT。Case不会因超时换键。内部草稿GET必须带Case派生的merchant/customer复合范围，公共`GET /api/v1/shop/drafts/{draft_id}`只试本人可信映射；他人/未知统一404，读不到底层customer或幂等键。重复提交恢复仍用原POST请求和原键，不按未知结果新建。

本批只有获取/创建草稿，没有支付、取消、发货接口或假成功按钮。下一批接入模拟支付/取消/到期竞争，原子发布已支付订单/行/账本/FREE槽；第四批再扩展单店多SKU。未来支付必须重新核对草稿有效期，并以本批固化金额为准，价格变化不重写已建草稿。

## 页面

商城提供全站搜索/分类、店铺和商品详情；选规格和1–max_quantity数量后请求报价，确认订单显示服务端金额与当前店铺。合成收货信息仅作展示，不是身份输入。提交后展示待支付草稿和真实到期时间，明确本批尚未开放付款。已有“我的订单/我的售后”继续原路径；工作人员导航不混入商城。主事实16–18px，不加角落说明、虚构营销或未实现购物车。

集中验证包括目录过滤/字面搜索/分页、下架/改价、数量、原金额无客户端覆盖、草稿重放/异请求冲突/并发、复合归属/Agent权限、到期、无支付副作用、协议生产消费者与桌面界面。真实商城支付及多行退款不算本批通过。
