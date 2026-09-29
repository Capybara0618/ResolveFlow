# 第五批：展示字段与正式页面视觉收口

> 后续范围更新（2026-09-29）：用户明确只需要桌面网页端。本文中的768/390验收是本批已经完成的历史兼容证据，不再作为未来实施目标；不得据此新增移动端页面、导航或专项适配。

先读[总约束](README.md)。依赖第二批稳定样本、第三批依据阅读；第四批离线已完成即可进行，live未授权不阻塞视觉。设计依据是用户参考图与 `docs/reviewer-optimization.md`，正式页面是唯一视觉验收对象。

## 1. 当前入口

- 正式页面：`web/src/App.vue`、`web/src/ui/workbench.css`、`tokens.css`、`ReviewDialog.vue`、`ReviewerWorkspace.vue`、`InvestigationSources.vue`、`InvestigationFindings.vue`、`ReviewIcon.vue`。
- `web/src/preview/ReviewPreview.vue` 与 `review-preview.css` 只是已有设计参考，不能只改preview交付；`preview/assets/headphones.svg`是示意资产，不是真实订单图片。
- 订单源：Commerce `order/OrderLineRow.java`、`OrderLineRepository.java`、`OrderLineReadService.java`、`internal/OrderLineController.java`；Case `order/CommerceOrderLineClient.java`；前端 `web/src/client.ts` 的OrderLine。
- 现有OrderLineRow有paidAt；前端OrderLine类型尚未列paid_at。先核对传输，不新增重复支付时间字段。
- Commerce已执行迁移当前到V6；新增迁移编号必须实时确认，不能覆盖V1–V6或假定后续没人添加。

## 2. 子步A：最小展示字段契约

本批决定只新增商品名与规格文本，不建设商品中心或订单修改API：

| 字段 | 权威归属/建议约束 | 缺失与历史兼容 |
| --- | --- | --- |
| product_name | Commerce订单行，VARCHAR(200)，API string最长200 | 新增nullable列，不改旧行；API可缺省或null，UI回退到SKU/“商品名称未提供” |
| variant_text | Commerce订单行，VARCHAR(200)，API string最长200 | 空白视为未提供；不能自行造颜色/规格 |
| paid_at | 已有Commerce时间字段，沿用UTC ISO时间 | UI仅在存在时显示；不猜交易流水号 |

执行顺序：

1. 查OrderLineSummary在core OpenAPI、Java两端、Python消费模型、fixture的所有定义（`rg 'OrderLineSummary|line_paid_amount' contracts/core agent/src java web`）。形成传播清单，不只改前端接口。
2. 扩展核心订单列表/单订单读取契约，明确字段可选/nullable与长度。沿用现有Schema表达null的方式；不要把历史响应变成缺必填字段错误。不修改旧compat协议来强行同步无关范围。
3. 追加Commerce迁移，只加列；历史订单保持null。改repository SQL投影、record及响应mapping，Case DTO同步透传。若增加record参数，所有构造fixture同步。
4. 展示字段默认不加入LineContext、MCP证据哈希或退款复核输入；如源码共用强制经过这些路径，逐项核对哈希/版本影响并保留旧引用兼容，不随手改变业务观察内容hash。
5. 仅对第二批manifest拥有的合成订单填入明确的示例商品名和规格；原7001等共享fixture不全表回填。种子可重复更新展示字段，不改变金额、时间、状态、revision或引用原文。
6. UI读真实API值；标题商品名、规格次行、SKU辅助显示。未知字段不编造，不用每个订单都显示同一耳机图。允许中性商品占位图并注明“商品示意/暂无图片”。

字段测试至少覆盖：旧行null正常返回；新合成行字段贯通；跨商户不泄漏；金额和分页排序未变；未知字段/长度的既有协议约束仍有效。

## 3. 子步B：锁定参考布局

参考图见 [reviewer-target.png](../../docs/reference/reviewer-target.png)（原始用户图片，仅作视觉参考）。若文件缺失，不编造自己看过图片；按以下尺寸/层级和已有V3设计实现并报告参考缺失。

保持浅底、白卡片、蓝色主动作，复用 `tokens.css`：当前主色#165dff、正文#14233e、分隔线#e5ebf4、背景#f7faff、圆角8px。间距基数4px，正文13–14px、小字12px、分区标题15–16px、工单标题20–22px；不降到难读字号来硬塞内容。

桌面以1680×960为主：顶部52px；四列为导航约208px、队列约294px、详情弹性、右侧摘要约330–354px。1440×900时可收窄导航/队列/右栏（约176/260/300），主详情仍应至少约620px；不足时转响应式，不让三块固定宽度挤穿主栏。复用现有grid，不重新引入UI组件库。

| 区域 | 默认展开内容 | 视觉/业务约束 |
| --- | --- | --- |
| 顶部 | 品牌、合成/mock提示、当前登录人、退出 | 不加无功能通知铃或虚构人员 |
| 左导航 | 审核队列、查询、真实状态筛选 | 数量来自接口，分页结果不冒充总数 |
| 队列 | 状态、两行诉求、编号、金额/时间（有数据才显示） | 选中蓝边；独立滚动；切换不丢失筛选 |
| 主详情首屏 | 工单标题/状态、商品摘要、客户原始诉求、材料 | 时间和状态明确；材料没有媒体则文本卡片 |
| Agent区 | 建议、关键来源陈述、冲突/缺口、引用入口、当前修订 | 蓝色浅底；不使用伪92%置信度；旧版显著失效 |
| 调查轨迹 | 少量关键事件；完整记录折叠 | 只按持久事件显示进度；不得演示动画假装调用 |
| 右侧 | 当前订单/支付事实、政策/复核状态、授权与执行摘要 | 缺会员/电话/渠道/额度数据就不显示假卡片；无依据不绿勾 |
| 底部审核区 | 当前允许的批准、补证、拒绝/人工方案 | 在主详情底部sticky；长内容仍可滚动到末尾，不遮挡正文 |

详情默认优先给业务信息，UUID/hash/JSON收在可展开元信息，保留可复制入口。尽量复用现有组件，只在App过长或重复职责确有需要时小范围拆组件，不能全页重写所有业务事件。

## 4. 子步C：响应式和真实操作

- 1280附近按实际可用宽度将右栏收进详情的“订单与执行信息”可展开区，不横向溢出。768可上下排队列/详情并提供清晰返回，390×844时单列、按钮换行，不能让最外层横向滚动。
- 桌面导航/队列可独立滚动；避免body与详情多个嵌套滚动区互相困住。sticky审核条只在所属详情区域内，预留底部空间。
- 批准必须有有效当前授权；UNKNOWN/已消费输入不能显示可重付入口；无授权时沿用人工方案/补证/拒绝，不伪造授权按钮。
- `ReviewDialog.vue`继续冻结打开时的版本，收到409解释工单变化并要求重新审阅，不能自动套最新版本重试批准。
- 补证/核验成功后刷新当前修订与列表状态；调查慢或失败显示真实原因，不无限spinner。Agent服务故障不抹掉已有客户材料。
- 所有可点击项有真实行为；没有业务接口的展示项用文字，不用假按钮。按钮禁用理由可读，键盘焦点可见，标签不单靠颜色区分；错误提示不泄漏内部凭证。

## 5. 集中验收与命令

```powershell
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
./java/mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service,case-service -am '-Dtest=OrderLineReadServiceDatabaseTest,OrderLineControllerTest,CommerceOrderLineClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_openapi.py agent/tests/unit/test_contracts_core_models.py -q
pnpm --dir web test
pnpm --dir web build
```

实际新增字段fixture/schema若还有定向测试需追加。字段涉及资金构造/LineContext才补对应复核测试，不默认重跑整个矩阵。已有Commerce未提交的RefundAcceptanceApiTest不是本批修改，不能夹带。

视觉必须实际打开正式页面并截图：1680×960、1440×900、390×844，另检查768宽下可操作。记录页面URL、样本ID、视口、mock/合成标识。至少覆盖lost-review和UNKNOWN；signed-conflict、waiting-info、success以及一次长文本/缺商品字段检查可集中在同轮。桌面核对四列层级和底部动作，窄屏核对无裁切、无横向溢出、引用/弹窗可操作。

需要支付动作的浏览器验收只使用第二批专用一次性样本，不批准唯一待审展示样本或共享库遗留授权。验证一次批准→结果跟进、一次补证→waiting、一次旧版本冲突、跨工单切换不串数据；用已有自动化回归覆盖重复操作，不为每个CSS值写镜像测试。

工具可用则使用浏览器自动化；工具不可用时明确视觉验收未运行，不能拿build成功当截图验证，不自行宣布第五批完成。

## 6. 交付与总收尾

交付 `reports/reviewer-visual/README.md`、正式页面截图、数据字段传播清单、旧值兼容说明、实测命令及结果；保留参考图版权/来源为用户提供，不把示意商品称真实附件。

最终todo只总结四批实际状态和报告链接。总交付应说明：审核员能做什么、数据从哪里来、哪些是mock/合成、未授权live仍未验证、已知失败/未运行。没有所有证据时不能写“全部优化已完成”。正常提交推送后报告SHA和远端状态，明确停止写入便于用户接管。
