# 后端深化与商品评价开发方案

2026-10-22，用户授权：先完成开发文档和预期图，再实施此前讨论的查询优化、商品评价/Redis、交易自动恢复。只使用现有三 Java 服务和 Python Agent；不新增库存、营销、真实支付、付费模型请求或微服务。当前进度只记 tasks/todo.md 顶部。

## 1. 当前事实和交付顺序

已核对 main=origin/main=932e067，暂存区为空，原四个脏文件及历史产物排除。本批不重做 Agent/RAG，不修改冻结实验。已有 RedisReviewQueueCache 仅被 ReviewQueueService.list 使用，正式网页携带 view/query/scope 后走 workspace，原压测不能代替当前入口验证。Commerce 商品列表逐个读商品/SKU，订单列表逐个组装详情，先选择有明确收益的小切口。

| 批次 | 子步 | 交付和验收 |
| --- | --- | --- |
| B1 查询 | B1.1 工作台缓存；B1.2 商品列表批量读取 | 正式带筛选入口命中缓存；按商家/人员/筛选/游标隔离；故障有限回源；商品列表 SQL 次数不随页内商品数线性增长；原报价重新读权威事实 |
| B2 评价 | B2.1 数据/领域；B2.2 内外接口与契约；B2.3 双端界面；B2.4 Redis | 已签收本人行评价、修改、商家回复、公共摘要/列表；并发唯一约束、版本冲突、退款保留；评分缓存和账号限流均可故障验证 |
| B3 恢复 | B3.1 有界扫描；B3.2 调度和运行接线 | 到期未付款持久关闭；UNKNOWN 只查询原收据并结算；重复执行不重复订单；中断后恢复；无收据保持 UNKNOWN，绝不自动发起扣款 |

每个独立小步先关键失败测试，再实现、针对验证、记录、精确提交并正常推送。批次报告包含通过/失败/未运行，禁止先功能全堆完再验证。现有订单查询优化若涉及大幅 DTO 重组，另拆后续小步，不能用商品优化冒充订单优化完成。

## 2. 查询和 Redis 约定

工作台采用现有 2 秒 TTL 的展示缓存；key 包含商家、当前人员、view、scope、规范化 query、cursor、limit，使用独立版本前缀避免旧键碰撞。先鉴权、校验参数/游标，再读缓存。命中也不赋予任何审批权限，所有写动作沿原数据库版本/归属复核。故障回源最多 8 并发，等待 100ms 后明确返回可重试 503；统计命中、缺失、错误、实际 DB 调用。读事务仅包围实际 DB 查询，避免 Redis 等待占用事务。

公共商品列表一次查商品和店铺，一次批量查这些商品可售 SKU，保持字面搜索、稳定游标、启停过滤、min 价格和原错误语义。商品详情/下单报价仍读权威数据。只缓存有界数据，不缓存任意搜索词组合，不以缓存价格决定支付。

评价公共首页与统计采用 MySQL 持久版本作为缓存代际，key 为 product/version；评价修改和回复与代际递增同事务，读方先读版本，因此晚到的旧写只能写旧代缓存。TTL 限制旧键寿命；Redis 故障回源数据库，设置短连接/命令超时，回源受并发门控保护。缓存仅含公开文字、评分、规格、时间及回复，不含 customer、line_id、幂等键。无效商品先验证公开可见性。

发布限流在 Case 按已认证账号和动作使用 Redis 原子固定窗口（Lua INCR+EXPIRE），允许每分钟 6 次评价/修改/回复；先检查合法身份，私有幂等重放不应变成重复业务写。Redis 故障对写入口返回可重试 503，不放开无限写入。数据库唯一约束和版本校验始终存在。没有用量即可不预设缓存收益指标。

## 3. 评价业务规则

- 评价属于 Commerce，Case 解析持久身份和可信 merchant/customer 映射；Gateway 沿原 Case 转发。Agent 不新增评价工具，也不能写评价/回复；用户文字不能成为退款资格事实。
- 首次评价要求本人已支付订单行、关联到当前商品 SKU，物流状态 DELIVERED；历史无法关联商品的行不可新建。每订单行恰好一条评价，数据库 line_id 唯一。退款不删除或隐藏已发表评价。
- 评分 1–5 整数；正文去首尾空白后 1–1000 字符；纯文本按 Vue 默认转义展示。公开昵称固定“已购用户”，只显示规格，不暴露账号及订单 ID。
- 首次提交 expected_version=0；修改使用当前 version。相同载荷重复请求返回原版本；不同载荷且旧版本返回 409。以订单行锁保证并发首评/修改串行，唯一键兜底；同一行不新增第二条。
- 买家可修改自己的评分/正文，版本递增；商家仅能对本店评价回复，不能改客户文字/分数或删除差评。回复为 1–1000 字符，使用当前评价版本；相同回复重放返回原记录，旧版本改回复 409。
- 公共列表按 review_id 倒序游标分页，默认 10、最多 20；摘要返回 count、average（无评价 null）、5 个星级计数。评价正文、摘要及 merchant 回复分别表达，不编造销量和评分。

## 4. 数据与接口合同

只追加 Commerce Flyway 迁移：product_review（review_id、line_id 唯一、product_id、merchant_id、customer_id、variant、rating、body、reply、version、created_at、updated_at）；product_review_epoch（product_id 主键、version）。索引 product_id/review_id 和 merchant_id/review_id。评价/回复及 epoch 同事务，金额/授权表不被评价写入。

| 公共路由 | 主体 | 语义 |
| --- | --- | --- |
| GET /api/v1/shop/products/{id}/reviews?before=&limit= | 匿名 | 可售商品评价首页/更多，包含摘要 |
| GET /api/v1/shop/orders/lines/{line_id}/review | 平台买家 | 本人评价或可评价原因；他人 404 |
| POST /api/v1/shop/orders/lines/{line_id}/review | 平台买家 | rating/body/expected_version；身份和金额不可注入 |
| GET /api/v1/merchant/reviews?before=&limit= | 商家 | 本店评价及回复 |
| POST /api/v1/merchant/reviews/{review_id}/reply | 商家 | body/expected_version，跨店 404 |

Commerce 对应 /internal/v1/shop/products/{id}/reviews 为只读公共来源；私有评价 /internal/v1/shop/orders/lines/{line_id}/review 要求 commerce:checkout + case-service 主体；/internal/v1/merchant/reviews 要求 commerce:fulfillment + case-service。body 用共享严格 DTO，新增 OpenAPI、JSON Schema、fixture 和 TS 类型，路由覆盖同步；数据库/HTTP/前端各自验收，不用 mock 代替实库。

## 5. 界面合同与预期图

预期图：[桌面原型](ui-backend-deepening-v1/index.html)。这是静态设计，数据为合成示例，不是当前页面或业务验收结果。

1. 商品详情在购买信息下增加“买家评价”：评分摘要、星级分布、文字/规格/时间、商家回复、加载更多、无评价和读取失败状态。
2. 我的订单详情每行显示“评价商品/查看评价”；点击后由后端重新返回资格，未签收显示原因；编辑展示实际版本，冲突保留输入并要求读取最新记录。保存成功显示原文和分数，网络失败不能显示成功。
3. 商家工作台增加“商品评价”，只列本店真实评价，右侧编辑回复。商家无删除入口；服务端拒绝跨店。所有主要文字至少 16px，1280/1440 桌面无横向溢出。
4. 付款待确认仍只提供查询原尝试/合法原请求恢复；自动对账没有新收费或“重新支付”按钮。后台失败仅展示事实，不把 UNKNOWN 画成失败/关闭。

## 6. 交易恢复约定

持久到期状态使用既有 CANCELLED + expired 关闭原因，公开投影保持 EXPIRED；只关闭 status=WAITING_PAYMENT 且 expires_at<=服务端时钟的草稿。PAYMENT_PENDING、PAID 不参与关单。追加迁移字段/索引，不修改旧迁移。

扫描每轮有上限，按下次检查时间公平推进，防止前批无收据记录饿死后续。UNKNOWN 查询原 attempt_id 的已持久收据：有收据调用原 settle，无收据只安排下次检查。绝不调用 provider.charge，绝不换 ID，金额不符保留 UNKNOWN。provider 查询在事务外，settle 仍使用原短事务锁与原子发布。每条独立捕获错误，不能一条坏记录阻塞整批；指标/错误只记录 ID 和安全原因，不输出敏感请求。

默认本地正式入口启用恢复；测试可显式禁用调度并直接驱动 tick。已有未知记录没有新扣款副作用；不启动模型/退款队列。重启/重复 tick/两执行者竞争应得到同一个业务结果。

## 7. 验收与证据

每小步补相关失败测试。重点：当前工作台缓存命中及人员/商家/筛选隔离；Redis 异常有限回源；商品批量结果一致；未签收/跨买家/Agent 拒绝；同一行并发首评、修改旧版本；跨商家回复拒绝；评分各星计数/退款后保留/缓存代际；账号原子限流；到期与付款竞争；UNKNOWN 缺收据不扣款、收据后崩溃自动发布/原子回滚、扫描公平性。

Java 使用仓库已有 Java21 和 Maven wrapper/Testcontainers，前端 pnpm test/build。隔离测试库可创建销毁，不修改演示库/旧卷；无付费 API。集中报告分别记录环境、实际命令、失败和修正、通过/跳过、未运行的网页/压测，不预设提升百分比。
