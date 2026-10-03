# 轻量交易上游与售后接入方案（待用户审查）

日期：2026-10-03。本文件响应用户关于商城上游、预期图和求职展示的讨论，是新增范围的建议稿，不是已批准实施指令。已交付售后五批继续以[todo顶部](../tasks/todo.md)及[验收报告](../reports/product-flow.md)为准。本轮只核对源码和编写文档，未生成图片、实现接口、迁移数据库、启动服务或调用模型。

## 1．定位与参照方式

保留ResolveFlow“售后调查Agent与可靠模拟退款”的求职项目定位，补齐用户产生订单的入口。目标体验是：当前商家店铺选商品 → 单行下单 → 模拟支付 → 模拟履约 → 本人订单申请退款 → 既有调查/补证/人工审批 → 模拟退款及公开结果。

可参考黑马商城课程中的商品、交易、支付等业务拆分思路，具体课程版本需后续核对；不以其源码、数据库、依赖或微服务清单替换本仓库。此次没有拿到经核实的课程源码，不主张已完成兼容分析或可以直接复用。使用第三方代码/素材前须确认具体来源和许可证。

先确定范围和交互合同，再画关键页面及失败状态，由用户审查图与文字，随后按纵向功能批次实施。位图不是接口或权限权威；继续复用v2白蓝桌面风格和现有组件，不重画已交付售后19项设计。

## 2．建议范围

| 能力 | 首版建议 | 明确边界 |
| --- | --- | --- |
| 商品目录 | 每个商家少量合成商品/SKU、名称、图片、类别、规格、CNY价格、上架状态；关键词与类别简单筛选 | 商品先受控种子维护，不做商品运营后台、推荐系统或搜索集群 |
| 下单 | 直接购买、确认规格及一件商品、服务端定价与持久草稿；重复提交幂等 | 首版一个SKU、一件、一个订单行，不做购物车、拆单或优惠分摊 |
| 模拟支付 | 当前草稿确认成功或明确失败、结果读取、幂等和并发支付/取消检查 | 本地合成支付，不接银行卡/第三方支付，不冒充真实到账；模拟按钮无选择成功退款的权限 |
| 模拟履约 | 管理员本商家已支付订单列表、一次模拟发货；只读物流事件和合成结论 | 不做库存、真实承运商、真实地址或实物退货；首版不需要专门履约服务 |
| 本人订单 | 待支付草稿、已支付订单、订单详情、支付/物流/售后三个状态维度 | 原客户申请和公开结果组件复用，不泄露授权或内部模型记录 |
| 演示场景 | 当前商家管理员在新订单第一次模拟发货前指定合成物流场景，服务端模板控制事件内容 | 只能演示配置，无任意SQL、原退款重置、改客户陈述或伪造核验；发货发布后不再修改场景 |

建议客户导航“店铺 / 我的订单 / 我的申请”；售后专员原导航保持；商家管理员新增“交易订单”，复用现有概览、人员和政策只读页面。客户仍绑定一个商家，无跨商家账号或平台管理员。第一版不收真实个人地址，用合成收货信息明确标识模拟履约。

“退货退款”必须涉及收货验货、退货物流和入库；本稿只做退款链路，页面继续写“申请退款”，不使用“退货已完成”等虚假状态。未发货取消支付与已支付售后退款不是同一种操作。

## 3．已核对源码：连接点与缺口

| 已有入口 | 实际能力 | 上游接入要求 |
| --- | --- | --- |
| [Commerce V1](../java/commerce-service/src/main/resources/db/migration/V1__commerce_order_read_model.sql) | orders/order_line/payment_ledger；订单和行paid_at均NOT NULL，订单行实付与账本是退款依据 | 不能直接塞无支付时间的草稿或伪造paid_at；推荐新增草稿表，支付成功后发布到已有表 |
| [Commerce V3](../java/commerce-service/src/main/resources/db/migration/V3__commerce_refund_local.sql) | line_refund/退款操作/inbox；FREE、RESERVED、CONSUMED与金额约束 | 发布新已支付订单时同时创建FREE退款槽，沿用旧执行路径 |
| [Commerce V6](../java/commerce-service/src/main/resources/db/migration/V6__commerce_shipment_adapter.sql)、[ShipmentReadService](../java/commerce-service/src/main/java/com/resolveflow/commerce/shipment/ShipmentReadService.java) | 按line_id读合成shipment/event及来源版本；不存在时返回缺失 | 新履约必须产出相同读取合同、真实存储版本与synthetic标记，不靠前端临时生成物流 |
| [OrderController](../java/case-service/src/main/java/com/resolveflow/caseservice/order/OrderController.java)、[CommerceOrderLineClient](../java/case-service/src/main/java/com/resolveflow/caseservice/order/CommerceOrderLineClient.java) | 公共订单GET经Case校验当前身份、内部SERVICE token查询Commerce；按主体范围过滤 | 追加交易门面，复用身份边界；现有GET不改成未支付/已支付混合数据格式 |
| [CustomerCaseService](../java/case-service/src/main/java/com/resolveflow/caseservice/casefile/CustomerCaseService.java) | 本人行资格根据PAID、活跃/已成功申请及可退金额计算 | 新支付行直接可读；若采纳首版发货后退款范围，资格和创建API都需加同一新订单规则，不能只禁用按钮 |
| [CaseService](../java/case-service/src/main/java/com/resolveflow/caseservice/casefile/CaseService.java)、[PolicySelectionService](../java/case-service/src/main/java/com/resolveflow/caseservice/policy/PolicySelectionService.java) | 以本人line_id创建工单，按订单支付时间和商家选择、钉住政策；创建记录与调度继续复用 | 金额、归属、支付时间必须来自服务器；不能请求体选择政策。新日期要实际验证政策覆盖 |
| [CustomerWorkspace](../web/src/ui/CustomerWorkspace.vue)、[client](../web/src/client.ts) | 正式客户订单/申请、问答及公开结果 | 新订单详情链接既有申请资格/创建/详情，不能重复开发售后页面 |

当前售后原型不是完整交易写模型，新增下单/支付入口不能只改UI或调用验收seed_line。迁移只追加，现有已支付订单、退款、run和政策hash不改。实施时读取实际最新迁移编号，不预先占号。

## 4．推荐数据组织与状态

Commerce继续拥有商品、交易、支付和模拟物流；Case继续拥有持久账号/商家、工单、归属、政策绑定、人工授权；Python继续拥有调查run，AgentScope生产循环不变。新增功能沿用Gateway、Case、Commerce三个Java进程与Python Agent，不引入商城的第二套登录、支付账本或售后库。

建议新增商品/SKU、checkout草稿、模拟支付尝试、交易幂等及模拟发货审计数据；确切表名和DDL在合同批准后设计。SKU属于唯一商家；草稿记录merchant/customer、固定订单UUID/行ID、商品及价格快照、状态/version、服务端到期时间。快照含展示图及原图来源，不能由客户提交任意外部URL；历史商品空图继续诚实显示未提供。

草稿状态建议PENDING_PAYMENT → PAID或CANCELLED/EXPIRED。模拟失败记录一笔确定失败的attempt，草稿在期限内仍可重试；每次明确新尝试用新attempt，同一尝试重试用同ID。首版模拟器在本地交易内确定结果，不额外创造支付UNKNOWN服务；HTTP响应丢失仍是结果未知，客户端必须查原草稿/attempt，不当作明确支付失败重新下单。

支付成功的同一Commerce事务：锁草稿/检查版本、期限、身份作用域和既有支付结果 → 写成功attempt → 插入orders及order_line（PAID、实际UTC paid_at、CNY整数分实付/快照）→ 插入payment_ledger（paid_amount、refunded=0、reserved=0、version）→ 插入line_refund FREE → 草稿PAID并关联相同order_id/line_id。任一写失败整笔回滚；成功记录与发布订单只能一次，不能先显示成功再异步补资金账本。使用现有唯一约束及追加关联唯一键，不使用跨库长事务。

到期基于服务端时间，读取/写入都能诚实表现EXPIRED；清理不是删除草稿或金额记录。并发支付/取消以同草稿行锁决定胜负，取消只能取消未支付草稿，不能将PAID改成CANCELLED。正式订单仍满足原paid_at非空合同，草稿列表由新增API读取。

交易、履约、售后分开展示：订单PAID不等于已送达，模拟物流LOST不等于自动批准，售后CLOSED_SUCCESS不抹掉原付款事实。已退款/占用金额仍从现有资金权威读取；不通过改order_status绕开历史PAID读取和退款验证。

所有创建/支付/发货有幂等key、规范化请求hash及主体绑定：相同key/body重放原结果，不同body冲突；另一客户即使撞key也不能读原结果。version与有效状态由服务端复核，前端金额、merchant、customer、paid_at、refund amount不是可写授权字段。

## 5．权限与公共/内部API草案

外部继续浏览器 → Gateway → Case交易门面（当前持久身份校验）→ Commerce内部交易入口（独立SERVICE写scope，作用域来自已验证主体）。Commerce不得接受USER token；内部路由不经Gateway暴露，Agent/MCP既有只读scope不能调用下单/支付/发货。Case不直接读取Commerce库，Python不写交易数据。

客户可浏览本商家上架商品、创建自己的草稿、支付/取消自己的未支付草稿、查询自己的支付及物流。管理员只能读/模拟发货本商家订单；REVIEWER默认无发货/场景配置权限。管理员这项交易权限不等于工单owner，售后审批仍须领取/接管及原业务/协作/身份版本。

下面是新API方向，均未实现；路径及字段在各批正式合同中落实：

| 外部接口建议 | 用途 | 保护要求 |
| --- | --- | --- |
| GET /api/v1/store/products及/{id} | 本商家商品及SKU | 服务器范围过滤、简单游标、下架处理 |
| POST /api/v1/customer/checkouts | 建立本人草稿 | CUSTOMER、sku及有效商品版、数量1、幂等；服务端价款 |
| GET /api/v1/customer/checkouts及/{id} | 待支付/已发布草稿与结果 | 本人范围、版本、到期、allowed_actions |
| POST /api/v1/customer/checkouts/{id}/payments | 模拟支付尝试 | 原草稿版/幂等，结果来自受控本地模拟器 |
| POST /api/v1/customer/checkouts/{id}/cancel | 取消未支付草稿 | 幂等/版/期限；PAID拒绝 |
| GET /api/v1/customer/orders/{id}/shipment | 本人合成物流 | 内部读范围复核，只返回客户公开字段 |
| GET /api/v1/admin/trade-orders及/{id} | 本商家交易工作区 | 当前MERCHANT_ADMIN，本商家分页与准确计数 |
| POST /api/v1/admin/trade-orders/{id}/dispatch | 第一次模拟发货及受控场景 | MERCHANT_ADMIN、原版/幂等、PAID、无退款占用/成功，发布后只读 |

新写入必须定义当前账号校验和内部委托边界，复用签名和锁序设计，明确已经到达事务的请求与账号停用的竞争语义；不承诺撤回已经开始的操作。外部网络调用在数据库长事务外，CommerceUnavailable返回503而不是伪造404或支付成功。合同、types、fixture、scope登记及实际路由覆盖同步追加，不删除旧断言。

## 6．物流、证据和政策如何连通

建议首版新店铺订单只有模拟发货发布后，才进入当前物流/损坏退款范围；未支付/未发货页面明确下一步，已支付未发货退款暂不实现。该新增门槛只适用于新来源订单，历史种子资格保持；若用户要未发货退款，必须另写对应政策和状态，而不能假装当前物流丢失政策覆盖。创建工单API与客户资格投影都必须检查权威新来源/发布状态，支付不同时等于发货。

这个约束也固定演示场景：只有第一次发货前可选，发货一次性持久发布合成shipment/event和source_version，从此只读；不在已经申请售后的订单中切换场景或改已有物流事件。交易版本、发货幂等、Paid/资金占用复核在Commerce本地事务保证。发布完整模拟轨迹是本地实验数据准备，不冒充真实物流随时间完成。

模板至少包括：明确LOST/无签收、DELIVERED但客户争议、IN_TRANSIT证据不足、DELIVERED并由客户报告损坏。不能让客户购买时选择“保证退款”；损坏不是物流枚举，仍靠客户材料与人工核验。管理员指定模板也不形成退款授权，Agent需实际读工具/政策，工作人员独立决定。

工单关联继续使用同一line_id/order_id/merchant/customer、原行实付及paid_at；物流观察带实际source_ref/source_version/content_hash，客户陈述、人工核验和模型推断分开。现有MCP读取、政策检索和引用验证复用。新商品类别/当前支付日期必须匹配实际导入政策；如无覆盖，明确拒绝/提示，不改支付日期、不借另一商家政策。确需新政策时追加不可变版本及索引，已有工单manifest/hash不变。

退款继续现有Case授权消费 → MQ → Commerce退款槽/预留 → 持久模拟provider → outbox/inbox回传。新交易模块不直接退款、不根据模型confidence支付、不重建退款操作。UNKNOWN保持原operation与占用，已消费输入冻结；成功行最多一次，不给“重新支付退款”按钮。

## 7．预期图清单与文字合同

建议先画6张页面图加2张状态板，配套同一份导航/字段来源/允许动作说明；用户确认后再实现。全部桌面1280/1440/1680，沿用v2品牌、侧栏、卡片、按钮和来源提示。业务金额/计数/状态只有实现时服务端可提供才显示。

| 设计 | 必须说明的入口、数据与去向 |
| --- | --- |
| U01 当前商家店铺 | 商品卡/简单筛选、登录商家；商品→U02，客户不能切到其他商家 |
| U02 商品详情 | SKU/价格/上架、数量1、合成商品图；立即购买→U03，无库存/优惠/好评率假数据 |
| U03 确认订单 | 本商家商品快照、服务器报价版、固定数量/总额；创建草稿→U04，冲突重查 |
| U04 待支付与结果 | 草稿号/服务端到期、模拟标记、可支付/取消；成功→同真实订单U05，超时先查原结果 |
| U05 我的订单与详情 | 待支付草稿与已支付订单清晰区分，支付/物流/售后独立，发货前原因；申请→现有客户表单，已有申请→现有详情 |
| U06 管理员交易订单 | 本商家待发货/已发货、详情/资金只读、首发受控模拟场景；不放隐式售后批准 |
| U07 交易状态板 | 下架/价格版冲突、重复点击、支付失败、到期、取消/支付竞争、响应未知、401/跨主体404 |
| U08 物流与售后状态板 | 未发货、三物流结论、客户损坏陈述、已申请/已退款/UNKNOWN；强调模拟与权限 |

图U05是在已交付订单基础上补交易详情，不重画客户问答/结果、专员调查和管理员人员页。付款结果/弹窗/状态板不必是独立菜单。图片中的数据只作合成示意，不能当业务测试；收口要看正式登录和真实API。

## 8．建议实施批次与门禁

| 批次 | 交付行为 | 关键验收 |
| --- | --- | --- |
| A：范围和设计合同 | 用户审查本稿→生成/审查8项预期设计→同步范围/规格，确定合同字段和权限 | 图文一致，模拟/物流退款范围明确，旧售后能力不重做 |
| B：商品与下单 | 新商品及草稿持久接口/页面，一件单行直接购买 | 两商家商品/草稿隔离、下架/价格版冲突、客户金额无效、创建重复重放/撞key不泄露；未付不能申请退款 |
| C：模拟支付与订单发布 | 新支付/取消页面，原资金表一次原子发布，现有订单可见 | 同attempt幂等、双标签支付只一成功、支付/取消一胜、期限拒绝、事务失败不残留半套账本、响应丢失可查同订单 |
| D：模拟履约与售后连接 | 管理员首发/场景页、本人物流/订单详情、旧申请入口衔接 | 新单发布前不可申请、发布后不可改场景、跨商家/角色拒绝、原scope Agent只读、新日期/类别政策正确、原历史数据保持 |
| E：正式跨角色收口 | 用户从店铺反复买不同新订单→付款→发货→四种场景→售后闭环；更新启动和演示说明 | 补证/核验/拒绝/成功/失败人工闭环、三资金状态与UNKNOWN同operation；mock/live分开记账，真实网页与桌面截图 |

每批包含契约/类型/fixture和相关有意义回归，集中验证后精确commit/普通push，不逐按钮打断用户；不以新测试数量替代实际流程。退款消费/并发/权限旧回归必须保留。记录通过、失败、跳过、未运行与合成ID；不清旧数据，不重复付款旧退款行，不为图开启收费模型。计划不估计未经核实的人天或效果提升。

## 9．实施前需用户确定的范围

推荐采用：单商家店铺/原账号、单SKU一件、直接购买、本地模拟支付、新单发货后物流/损坏退款、管理员首发及受控场景、商品种子维护、六页两状态板、原三Java进程及Agent、先设计再按批实现。用户若同意，这些才成为后续范围更新依据；本稿不自动修改core-scope中“商城非核心”的现有约定。

验收完成才能宣称“商品到售后的可运行闭环”；仍不能宣称完整电商、真实支付/履约、库存一致性、实物退货或生产高可用。求职重点继续是可解释的交易/资金一致性、身份隔离与Agent调查工程，而不是功能或微服务数量。

## 10．本轮文档核验

实际通过`agent/.venv/Scripts/python.exe -`执行pathlib/re脚本核对本稿、README及plan/handoff/todo共147个本地链接，引用源码均存在；`git diff --check`通过。首轮校验读取SQL未指定UTF-8，在Windows默认GBK下失败，显式UTF-8重跑通过；未改源码解决编码问题。Git main跟踪origin/main，fetch后0/0，本轮精确提交上述五个文档并正常推送。不运行业务测试、浏览器操作或付费调用，本稿中的API/表/界面仍是方案。
