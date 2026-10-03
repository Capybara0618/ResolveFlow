# 第五批：本商家交易、模拟履约与购物售后政策

2026-10-03，承接既定六批M09/M10/M11，复用第四批，不重选技术或扩大商城。本文是本批业务协议；完成状态只记tasks/todo.md。

## 履约事实与事务

仅已成功支付并由checkout发布的合成订单支持首次整单模拟发货。追加V14持久order_fulfillment，付款成功同事务创建NOT_SHIPPED/version=1及每行shipment/ORDER_PAID事件；只为已付checkout旧样本且全部行无shipment的订单补充这一新事实。原订单/账本/槽/原shipment及事件不修改；旧种子物流继续真实读取，缺失不等同未发货。付款UNKNOWN未发布订单不能发货。

NOT_SHIPPED只表示本地订单未执行模拟发货，不代表外部承运商结论；carrier_conclusion=UNKNOWN。首次发货生成各行SIMULATED_SHIPPED事件、IN_TRANSIT/version=2，时间取服务器Clock，synthetic恒true。不生成签收/丢失、真实运单或任意模板选择。全部行与履约头同事务，部分失败全部回滚；事件只追加。已发布不能改模板、改原事件或再次发货。

写锁序：本订单payment_ledger→order_fulfillment→按line_id排序所有line_refund。只允许总账refunded=reserved=0且各行FREE；任何REFUNDED/RESERVED/UNKNOWN或不完整槽拒绝。与现有退款接受共用账本锁，退款占用先赢则发货拒绝；发货先赢则后续退款调查看到新物流版本，不放宽退款资格或自动审批。尚未消费的申请可以存在，物流变化须由既有证据复核/新调查处理；Commerce实际建立退款占用后阻止发货；Case授权消费与异步送达Commerce之间不宣称存在分布式原子履约锁。发货不改Case输入revision/旧政策钉住/资金金额。

请求expected_version必须为正整数，Idempotency-Key为1–128字母数字下划线连字符。同订单原key+actor+expected_version重放原成功回执；同key异载荷或新key再次发货409。原响应丢失只查询/重试原请求，不能换key。事务内再次核验商家归属；跨店/不存在统一404。商家停用及账号身份版本由Case现有身份解析拒绝。Agent没有该范围的任何读写权限。

## API与字段

- 公共管理员：GET /api/v1/merchant/orders（status/cursor/limit），GET /api/v1/merchant/orders/{order_id}，POST同路径/simulated-shipment（expected_version+Idempotency-Key）。只有MERCHANT_ADMIN，商家/actor来自持久身份，客户与专员403；不接受自报商家或actor。
- Commerce私有同路径前缀/internal/v1/merchant/orders，由case-service且commerce:fulfillment调用。列表/详情带可信merchant_id；发货command含merchant_id/actor/idempotency_key/expected_version，不向公众暴露请求key。
- 本人买家GET /api/v1/shop/purchases/{purchase_id}/fulfillment；Case核验本人Purchase再读取Commerce按merchant/customer/order_id限定的/private shop订单履约。已付款才存在，其他主体404；旧客户端协议不增必填成员。
- Fulfillment：order_id、status、synthetic=true、version（历史非可写null）、updated_at（无事实null）、lines[各行line_id/status/carrier_conclusion/source_version/events]。NOT_SHIPPED/IN_TRANSIT/DELIVERED/LOST/UNKNOWN分开；多行历史不一致汇总UNKNOWN，保留逐行事实。未发现物流不造事件。
- MerchantTrade：purchase（既有CheckoutPurchase全部不可变行/退款汇总）、fulfillment、line_aftercare、can_ship、blocked_reason。line_aftercare按本订单每行真实line_refund投影FREE/RESERVED/CONSUMED/MISSING与refunded_amount/reserved_amount；缺槽为MISSING/null金额，不能装作无占用。同行只能全量退款，RESERVED表示金额占用，不代表已退款。列表items/next_cursor；仅真实已付订单，待付款草稿不混成可发货订单。可按NOT_SHIPPED/IN_TRANSIT/DELIVERED/LOST/UNKNOWN筛选，1–48，游标绑定商家与筛选，任一依赖故障不装作空列表。

## 政策与申请

追加两商家购物政策不可变版本，覆盖2026-10-01起的支付时间，effective_to=null。不改六个历史bundle正文、hash、时间或已钉住manifest；旧订单按paid_at选择原版本。新版本包含：未发货整行全额退款需当前持久NOT_SHIPPED事实；发货后仍按物流异常/人工核验损坏规则，不把所有在途无条件退款。每次只退该行全部数量/实付；同行一次、整单已退+预留上限、UNKNOWN原占用继续有效。不同理由不改变主体或金额权限。

RAG索引通过既有导入/index入口使用新精确manifest/hash，不以改名旧索引冒充完成；新调查读NOT_SHIPPED/ORDER_PAID事实并引用钉住政策。人工审批仍是唯一产品最终退款决定。新增未发货诉求在公开表单使用明确文字，Agent建议须有来源，模型confidence不是授权。政策引用与实际状态/版本变化要复核；不能把原404物流缺失当退款依据。

实现入口为UnshippedRefundCheck：REFUND建议引用R-UNSHIPPED-001时，在已有行归属/金额检查后读取Case专用本人履约接口，以订单ID、商家、客户和目标行限定，要求当前头/行NOT_SHIPPED/version1、UNKNOWN承运商结论及唯一ORDER_PAID事件。物流404拒绝建议，故障503不伪造缺失。人工批准按授权固定的proposal_id重读原建议，再读取当前事实；变更409且不写审批，依赖故障503，不持有Case/账号写锁跨网络调用。旧物流规则不增加购物依赖。当前事实复核不是分布式事务，也不保证跨服务读取后外部事实永远不变化；最终资金仍由Commerce账本/槽锁守住。新政策的Agent建议仍须有效钉住引用，人工建议同样复核。


## 页面及集中验收

M10管理员“交易订单”，保持已有商家/队列/人员/政策导航，不提供私有跨店切换。M11全部商品、原实付、履约、逐行售后及明确首次模拟发货确认，长编号展开。买家M09显示真实物流、待发货说明与已有逐行申请；主事实≥16px，1280/1440/1680桌面无横向溢出。未知写响应保留原请求，不自动第二次发货。未做库存、真实支付/物流、模拟签收、移动端、平台超级管理员。

AdminTrades在请求发送前，将order_id、原key、expected_version保存至当前浏览器sessionStorage，按商家和账号sub隔离（解码仅用于本地隔离，权限始终服务端核验）。重开页面只读取原订单，管理员显式重试同键同载荷；401保留原请求，确定拒绝则清除被拒绝请求并要求刷新，成功后的后续GET失败不反转为未知发货。无法保存或原记录损坏时阻止新写；关闭浏览器会话可能丢失本地恢复信息，不承诺跨设备恢复。订单状态由服务器再核验，不能据本地记录生成履约事实。

“查看此订单的售后工单”按order_id进入已有本商家公共队列全部阶段查询，未申请时显示空结果；不把商品行ID传给只支持订单号的旧搜索，也不将退款槽状态冒充工单处理进度。买家履约独立读取，故障可重试而不隐藏付款或售后资格；旧请求受页面/读取代次保护，不覆盖新订单。公开申请表用明确退款原因文字覆盖已付款未发货，不增设自动审批理由菜单。

先隔离实库失败回归归属、重复/不同键、版本、占用/已退、全部行回滚及竞争；再接协议/fixture/Case及网页，功能批次集中验证。保留数据部署，新增专用样本发货和只读原历史核验，不重置已付/退款订单；本批不为截图启动Live，第六批才集中购物→申请→Agent/RAG→人工→退款网页闭环。报告分别记录实际通过、失败与未运行。
