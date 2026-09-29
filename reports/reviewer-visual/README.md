# 第五批交付：展示字段与正式页面视觉收口

2026-09-29 执行（DSH）。依据 [`tasks/dsh-reviewer/05-fields-visual.md`](../tasks/dsh-reviewer/05-fields-visual.md)。截图全部来自**正式页面 + 真实接口**（demo gateway `http://127.0.0.1:8180`），不是 preview、不是构建产物。

## 1. 商品展示字段贯通（子步A）

只新增两个展示字段，不建商品中心、不加订单修改 API。

| 字段 | 归属 | 约束 |
| --- | --- | --- |
| `product_name` | Commerce `order_line`（V7 新增列），`VARCHAR(200) NULL` | 契约 `OrderLineSummary.product_name`，`type: [string, 'null']`、`maxLength: 200`；可缺省或 null |
| `variant_text` | 同上 | 同上；空白视为未提供 |
| `paid_at` | **已有**字段，未新增 | 前端类型补齐后仅在有值时显示；不猜交易流水号 |

传播清单（`rg 'OrderLineSummary|line_paid_amount' contracts/core agent/src java web` 定位实际路径）：

| 层 | 文件 | 改动 |
| --- | --- | --- |
| 迁移 | `java/commerce-service/.../db/migration/V7__commerce_order_line_display_fields.sql`（新） | 只 `ADD COLUMN` 两列，NULL 无默认；V1–V6 未改 |
| Commerce 行 | `order/OrderLineRow.java` | 加 `productName`/`variantText` |
| Commerce 查询 | `order/OrderLineRepository.java` | **只**在 `findVisible`（供订单视图）投影两列；`findContext`（供退款重算的 LineContext）**不加** |
| Commerce 响应 | `internal/OrderLineController.java` | `OrderLineSummaryResponse` 加两个 `@JsonProperty`，沿用 `NON_NULL`（缺省即省略） |
| 核心契约 | `contracts/core/openapi-commerce.yaml` | `OrderLineSummary` 加两个可选成员 |
| 核心契约 | `contracts/core/openapi-case.yaml` | 同一 payload 的公共定义同步（`test_the_internal_order_view_is_the_public_order_view` 要求两份逐字相同） |
| Case 消费 | `order/CommerceOrderLineClient.java` | `OrderLineSummary` 加两个可空成员，**只对这两个成员** `@JsonInclude(NON_NULL)`：历史行仍按改动前的成员集回答；若整体 NON_NULL，会把必填成员里的 null 也吞掉 |
| Case 公共响应 | `order/OrderController.java` | 直接透传该 record，无需改动 |
| 前端类型 | `web/src/client.ts` | `OrderLine` 加 `product_name?`/`variant_text?`/`paid_at?` |
| 前端呈现 | `web/src/ui/order-line-format.ts`（新）、`web/src/App.vue` | 商品名作标题、规格次行、SKU 辅助；缺失回退 SKU，二者皆无才显示"商品名称未提供" |
| 演示种子 | `scripts/reviewer_demo.py` | 新建样本行写入两列；`prepare` 对 manifest 拥有的行做幂等回填（只 Update 这两列） |

**没有动** `LineContext`、MCP 证据哈希或退款复核输入：展示字段不进 `findContext`，因此金额、观察内容 hash 与引用原文都不受影响（`OrderLineReadServiceDatabaseTest` 里有一条断言把这件事钉住）。

实测：`SELECT line_id, sku, product_name, variant_text, …` 显示 7 条 manifest 行有值，旧行与被退役的行仍为 NULL，共享 fixture `7001` 保持 NULL（未全表回填）。

## 2. 页面行为（子步B/C）

- 1680×960：顶栏 52px；四列 = 导航 208 / 队列 294 / 详情弹性 / 右侧 354（与手册一致，沿用现有 grid 与 `tokens.css`，未引入组件库）。
- 1440×900：`max-width:1499px` 规则把导航/队列收到 172/258，右栏移到详情下方并分成两列（实测详情仍宽于 620px）。
- 1280 附近：右栏改为**可展开区**"订单与执行信息"。这是标记层实现（`<component :is="contextFolded ? 'details' : 'aside'">` + `matchMedia('(max-width:1299px)')`），不是 CSS 覆盖——关闭的 `<details>` 无法用 CSS 重新打开，常开的也无法折叠。
- 768：队列变成横向滚动条、详情在下，并出现"← 返回队列"（`data-test="back-to-list"`，仅 ≤850 显示）。
- 390×844：单列、按钮换行、无横向滚动（`captures.json` 中 `horizontal_overflow=false`）。
- 右侧只显示有数据的卡片：无会员/电话/渠道/额度就不出现假卡片；支付渠道与流水仍写"暂未提供"。
- 底部审核区在详情内 sticky（`margin-top:auto` + `bottom:0`），≤850 改静态；不会遮住正文。
- 批准/补证/拒绝仍由服务端 `allowed_actions` 与授权状态决定；UNKNOWN/已消费不显示可重付入口（unknown-refund 截图右侧为"已消费（不可重审）"）。
- `ReviewDialog` 继续冻结打开时的版本，409 时解释并要求重新审阅（沿用第一批行为，未改）。

## 3. 截图（`reports/reviewer-visual/`）

| 文件 | 视口 | 内容 |
| --- | --- | --- |
| `lost-review-1680x960.png` | 1680×960 | four 列层级、商品名/规格/SKU、右侧事实、底部动作 |
| `lost-review-1440x900.png` | 1440×900 | 收窄后右栏下移，主线不挤 |
| `lost-review-1280x900.png` | 1280×900 | 右栏不再占列 |
| `lost-review-fold-1280x900.png` | 1280×900 | 滚到"订单与执行信息"可展开区（可点开） |
| `lost-review-768x900.png` | 768×900 | 队列横向滚动 + 返回队列 |
| `lost-review-390x844.png` | 390×844 | 单列、换行、无横向溢出 |
| `unknown-refund-1680x960.png` / `unknown-refund-390x844.png` | 1680 / 390 | UNKNOWN 样本：退款对账中、授权已消费、无重付入口 |
| `waiting-info-1680x960.png` / `waiting-info-768x900.png` | 1680 / 768 | 等待补证态与窄屏可操作 |
| `missing-fields-1440x900.png` | 1440×900 | 无商品名/规格的历史行：标题回退 SKU，不编造商品名 |

每次截图的 `scrollWidth/clientWidth`、页面标题、状态标签、Agent 摘要都记在同名 `*-captures.json` 里。

## 4. 命令与结果

```powershell
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
./java/mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service,case-service -am `
  '-Dtest=OrderLineReadServiceDatabaseTest,OrderLineControllerTest,CommerceOrderLineClientTest,OrderApiTest' `
  '-Dsurefire.failIfNoSpecifiedTests=false' test
# Tests run: 17, Failures: 0 (含新增：展示列可空/贯通、命名行 vs 历史行的成员集)

agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_openapi.py agent/tests/unit/test_contracts_core_models.py -q
# 238 passed

pnpm --dir web test    # 68 passed（新增 order-line-format 5 项、app.spec 覆盖回退与缺字段）
pnpm --dir web build   # vue-tsc + vite build 通过
```

截图命令（可复制）：

```powershell
agent/.venv/Scripts/python.exe scripts/reviewer_screenshots.py `
  --proxy http://127.0.0.1:8180 --port 5174 `
  --case 406a0ef1-1c16-4442-b077-14641c971f65 `
  --viewport 1680x960 --viewport 1440x900 --viewport 390x844 `
  --label lost-review --out reports/reviewer-visual
```

## 5. 未运行 / 限制

1. **真实支付动作的浏览器验收未做**：本次只做了只读浏览（打开工单、展开引用、切换视口）。"批准→结果跟进""补证→waiting""旧版本冲突"的浏览器端验收需要批准一个专用一次性样本；本批没有为它消耗 UNKNOWN/展示样本，已在第二批用 API 完成同链路验证（见 `reports/reviewer-demo/README.md`）。这是本批唯一未运行的验收项。
2. 商品图仍是中性占位图标并注明"商品示意"；没有媒体上传，也没有每个订单都显示同一张耳机图。
3. 参考图 `docs/reference/reviewer-target.png` 未逐像素比对：本批按手册给出的尺寸/层级与现有 V3 设计实现，并以实际截图人工核对。
4. 运行截图期间本机 Docker 曾被整体关闭（容器 `Exited (137)`），已重启 demo 栈后重取；共享环境未被本批改动。
