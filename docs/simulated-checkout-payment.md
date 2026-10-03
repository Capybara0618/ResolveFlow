# 模拟付款与本人交易

2026-10-03，第三批M07–M09。沿用[目录与草稿](catalog-checkout.md)、平台买家可信复合归属和原售后；不做购物车、多行、发货或真实支付。所有付款明确为本地模拟，无模型调用、外部扣款或银行卡输入。

## 状态与事务

草稿固化金额、规格、数量、商品/店铺名称及类别。追加迁移，不修改V10：持久状态WAITING_PAYMENT、PAYMENT_PENDING、PAID、CANCELLED；只有WAITING_PAYMENT在到期后投影EXPIRED。付款前锁草稿核对本人归属与服务端时钟。到期或取消不能开始付款；进入PAYMENT_PENDING后禁止取消，到期也不能把未知付款当成失败。PAID不可回到待付款。

付款采用三个短事务边界：①锁草稿，记录唯一尝试和预分配订单/行ID，草稿进入PAYMENT_PENDING；②在该事务外调用持久本地模拟provider，以原attempt_id幂等生成收据；③锁同草稿和原尝试，成功时同一Commerce事务写orders/order_line/payment_ledger/line_refund并关联PAID。orders和line的paid_at仍非空，使用成功收据时间；账本paid_amount等于原草稿金额，refunded/reserved为0，每行FREE一次，不造物流。

尝试状态UNKNOWN、SUCCEEDED、FAILED。UNKNOWN表示尚未有已持久的确定结果，不能新建另一尝试、取消或释放；查询只读取原provider收据并结算原尝试，不发起扣款。若进程在provider调用前中断，查询仍UNKNOWN，用户可明确重试原POST（同key）继续原attempt_id。若响应在收据持久后丢失，查询即可恢复。模拟provider平常固定成功；确定失败及故障仅由隔离测试注入，不提供公开故障参数。FAILED在未到期时回WAITING_PAYMENT，显式再付才允许新key；到期后不能再付。确定失败不产生订单/账本/槽。

每草稿Idempotency-Key唯一；同key重放同尝试，包括失败结果。成功草稿不接受新付款键，未知草稿不接受不同键；原键可恢复。取消无需键，WAITING_PAYMENT原子变CANCELLED，重复取消返回同状态；与付款竞争共享草稿锁，最多一方成功。金额、customer/merchant/buyer、provider结果、订单ID不能来自公共请求。收据金额冲突拒绝结算，保留原UNKNOWN。

## 本人交易入口

新增Case `/api/v1/shop`：GET purchases（store_id/status/cursor/limit）、GET purchases/{purchase_id}、POST drafts/{draft_id}/payment（Idempotency-Key及严格空对象）、GET drafts/{draft_id}/payment、POST drafts/{draft_id}/cancel（严格空对象）。仅当前平台买家；旧客户/工作人员403，缺会话401，他人/未知404。Case从持久绑定派生merchant/customer，公共查询不能自选customer。Commerce对应内部路由需要commerce:checkout及case-service部署主体，Agent无权读取私有交易或写付款。

交易列表将新草稿与原本人已支付订单合并，已发布草稿只出现一次。以创建时间和purchase_id降序按店分页，再由Case按可信店铺合并；cursor绑定当前buyer/归属/筛选，不能跨账号或换筛选复用。草稿purchase_id为draft_id，历史订单为order_id；响应不含customer或请求键。详情返回真实支付尝试、支付订单/行及原金额；历史未提供的名称/插画/单价保持null，不补造。

第三批页面：付款页明确待付金额/截止时间及模拟付款；结果不确定时只查原尝试或重试原请求。我的订单包含待付款、结果待确认、已付款、已取消、已到期及本人历史订单，并可按店筛选、加载更多、打开详情。已付订单行可进入原售后资格/申请流程，资格仍由现有服务端计算；当前未发货与当日支付政策留第五批补齐，本批不宣称新购物已完整支持退款。

集中验证：重复/并发付款、取消竞争、到期、调用前/收据后中断、确定失败再付、原金额/原尝试恢复、原子发布失败回滚、跨主体拒绝与Agent权限、旧订单/退款账本兼容；桌面状态及迟到响应验证后普通提交推送。
