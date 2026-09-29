# 第三批交付：政策与工具依据可读

2026-09-29 执行（DSH）。依据 [`tasks/dsh-reviewer/03-readable-sources.md`](../tasks/dsh-reviewer/03-readable-sources.md)。依赖第二批已跑通的稳定 mock 样本（`reports/reviewer-demo/`）。本批**只改前端**（外加一处 Vite 演示代理配置和截图工具），未改 Java/Python 生产代码或契约。

## 1. 改了什么

| 文件 | 作用 |
| --- | --- |
| `web/src/ui/investigation-format.ts`（新） | 引用身份的**唯一**比较口径（政策五项 / 证据四项）、来源投影、五个工具的业务摘要、条款原文分句与限制性表述标记 |
| `web/src/ui/PolicyCitations.vue`（新） | 方案引用的政策与证据列表；可定位的引用才是按钮，其余如实说明为何不能定位 |
| `web/src/ui/InvestigationFindings.vue` | FACT/INFERENCE/CONFLICT 分项与"核对依据"改为按证据四项全匹配 |
| `web/src/ui/InvestigationSources.vue` | 工具摘要改用共享模块；保留全部原有提示 |
| `web/src/ui/ReviewerWorkspace.vue` | 政策依据改为三层展示 + 条款聚焦；review-context 改为父层传入 |
| `web/src/App.vue` | review-context 只请求一次并由父层下发；方案引用改用 `PolicyCitations`；聚焦请求下传 |
| `web/vite.config.ts` | 代理目标与端口改为 `VITE_API_PROXY` / `VITE_PORT` 可选覆盖，默认值不变 |
| `scripts/reviewer_screenshots.py`（新） | 用已装的 Chrome + DevTools 协议对**正式页面真实接口**取多视口截图 |

## 2. 引用与原文定位（子步A）

统一口径：政策引用 = `bundle_id/version/rule_id/chunk_id/content_hash` **五项**；证据引用 = `observation_id/source_ref/source_version/content_hash` **四项**。缺任一项就不是"已核对"，页面不做降级比较。

- 政策条款只从**已有** `review-context` 的 `policy_rules` 取；App.vue 每个工单只请求一次，通过 props 下发（不再有按引用逐个请求）。
- 点击引用：展开绑定政策区、`scrollIntoView` 到该条款、把键盘焦点移到条款标题（`h4[tabindex=-1]`）。标题是条款名，版本/规则/片段/摘要放次行。
- 五项不匹配 → "该引用未能匹配当前绑定政策；不展示最新政策或同名条款来代替"，并保留该引用已记录的全部元信息。
- 缺项（历史方案） → "该引用未记录完整政策身份（缺少 …），无法与当前绑定政策核对"。
- 本视图拿不到绑定政策（例如客户角色） → 只显示"暂无可读取的绑定政策，无法核对上述引用"，**不**谎称引用不匹配。
- `InvestigationFindings.vue` 的材料分支改为先取 `proposal.evidence_refs` 中该 observation_id 的完整引用，再与材料四项比对：一致才展示正文与人工核验结论；四项不一致显示"该引用与当前材料或已保存记录的来源、版本或内容摘要不一致"并且**不展示**当前内容；历史缺引用显示"此历史方案未记录完整引用"。工具分支继续要求四项与已保存观察相同。
- 旧方案仍可读，并显式标注失效（`STALE` 提示 + `revision-progress`）；其引用若不在当前调查记录里就显示未提供。本批未新增历史修订选择器。

## 3. 工具业务摘要（子步B）

摘要取自**第二批真实保存的 observation.result**，字段从数据与 core schema 读出，不猜：

| 工具（实际名称） | 默认摘要 |
| --- | --- |
| `get_order_context` | 订单行、SKU、类别、数量、实付/已退/预留（整数分，`0.00 CNY` 与"未提供"分开）、支付时间、订单状态 |
| `get_shipment_trace` | 记录状态、承运商结论、是否合成、关键事件（时间+版本）、更新时间、分页是否到底（不把 SIGNED 说成客户认可） |
| `get_refund_status` | 退款状态（FREE/RESERVED/CONSUMED/RELEASED）、行、实付/已退/预留、执行编号 |
| `get_case_evidence` | 材料条数、材料类型、材料版本，并说明**该工具只返回引用、正文见材料区、引用不等于已核验** |
| `get_policy_manifest` | 政策归属商家、生效起点、绑定 bundle/摘要前缀/safety epoch |
| `search_policy` / `read_policy` | 检索词、命中数、前 5 条标题与 bundle/version、相关度；明确"相关度是检索排序，不代表退款资格或模型置信度" |
| 未识别工具 | 不产出摘要，保留原始结果与来源信息，不抛错、不空白 |

手册表格里的 `get_order_line` / `read_policy` 在实现中是 `get_order_context`、`read_observation`（`agent/src/resolveflow/harness/actions.py` 的 WHITELIST 与本地能力），按手册"类/路径轻微变化 → 定位相同职责并报告实际路径"处理：摘要按**实际**工具名分派，未知名字走原文回退。

保留的提示（逐项仍在页面上）：`NOT_SCHEDULED`、`UNAVAILABLE`、空观察、`error_code`、`body_omitted`（正文明说超过 32768 字节上限）、`truncated`（明说仅前 40 条）、`model_provider` 缺失、mock 标签。省略内容不会被摘要或 Agent 文本补造。

## 4. 条件、例外与三层（子步C）

条款区固定三层且互不合并：

1. **① 原始条款（权威文本）** —— 只渲染已存文本。分句后**仅把原文本身含"例外/除外/但/不得/必须/须/仅在/方可"的句子加边标注**，并说明"已按原文标出；是否适用由人判断，本页不作推断"。不做关键词推断结论、不调用模型生成权威摘要、不改写原文。
2. **② Agent 解释与适用判断** —— 当前修订方案的 `summary`，明确标注为模型整理；旧修订的解释标注"已失效，仅供比对"。
3. **③ 服务端复核结果** —— 只显示现有 `proposal.status` / `refusal_reason`，并注明"资格与金额由服务端判定；本页不计算退款资格"。没有结构化 Java 规则项时不新增前端资格计算器。

引用了某条款的方案，会在该条款上显示"本方案引用此条款"（按五项身份判定）。

## 5. 实际截图（正式页面 + 真实接口）

用 `scripts/reviewer_screenshots.py` 打开真实前端（`VITE_API_PROXY=http://127.0.0.1:8180`、5174），真实登录 demo gateway，通过页面自身的"按工单编号查询"打开真实样本后截图。全部 1680×960、无横向溢出。

| 截图 | 内容 |
| --- | --- |
| [`lost-review-1680x960.png`](reviewer-demo/screenshots/lost-review-1680x960.png) | lost-review 工单首屏：Agent 建议、引用政策条款、人工接管区 |
| [`lost-review-citation-1680x960.png`](reviewer-demo/screenshots/lost-review-citation-1680x960.png) | **点击"承运商判定丢失"引用后**：绑定政策区自动展开、滚动到该条款、焦点落在条款标题；三层（①/②/③）可见；该条款标"本方案引用此条款" |
| [`lost-review-exception-1680x960.png`](reviewer-demo/screenshots/lost-review-exception-1680x960.png) | 同一页面滚到 `R-LOST-EXC-001`：**例外原文完整可见**（"例外：本规则不适用于支付金额超过 500000 分的订单行…必须转人工。"）并按原文标注限制性表述 |
| [`signed-conflict-1680x960.png`](reviewer-demo/screenshots/signed-conflict-1680x960.png) | 签收冲突样本：建议人工复核、无待审授权、材料待人工核验、引用 `R-SIGNED-001` |
| [`signed-conflict-citation-1680x960.png`](reviewer-demo/screenshots/signed-conflict-citation-1680x960.png) | 点击 `R-SIGNED-001` 后定位到"已签收"条款原文 |
| [`damage-review-1680x960.png`](reviewer-demo/screenshots/damage-review-1680x960.png) | 破损样本：建议补充信息、**没有任何政策引用**（该商家钉住政策无破损规则）、只列证据引用并提示"四项齐全才算完整引用" |
| [`waiting-info-1680x960.png`](reviewer-demo/screenshots/waiting-info-1680x960.png) | 追问样本：WAITING_CUSTOMER 与下一步说明 |

截图证据同时记录在 `reports/reviewer-demo/screenshots/*-captures.json`（含每次截图的 `scrollWidth/clientWidth` 与 `horizontal_overflow`）。

## 6. 命令与结果

```powershell
pnpm --dir web test      # 63 passed (11 files)
pnpm --dir web build     # vue-tsc + vite build 通过
```

新增/改写的测试覆盖手册点名的负例：

- `web/tests/investigation-format.spec.ts`（16）：政策五项**逐项**改变都不能定位；同名跨版本/跨 bundle 条款不串；证据同 ID 不同 version 或 hash 不算已关联；缺项报 `INCOMPLETE`；金额整数分且 `0` 与缺失分开；`SIGNED` 不被解释成客户认可；相关度不被当成资格/置信度；未知工具返回空摘要且标签诚实；条款分句保持原文且只标限制句。
- `web/tests/policy-citations.spec.ts`（5）：五项全等才渲染可点击按钮并 emit 身份；不匹配展示"未能匹配当前绑定政策"；缺项列出缺失成员且不展示任何条款正文；无绑定政策时给出说明；证据引用缺项告警。
- `web/tests/investigation-findings.spec.ts`（5）：四项全等才展示材料正文；hash 不同拒绝借用当前材料；历史缺引用明确不可核对；回退到已保存工具记录并给摘要+原文；缺证据清单与"无绿勾"。
- `web/tests/reviewer-workspace.spec.ts`（8）：三层分离、限制性表述标记、被引用条款标记与聚焦展开。

Java/Python 未变动，按手册"纯前端之后不重复其未变测试"未重跑；第二批的 Java 8 项与 Python 全量结果见 `reports/reviewer-demo/README.md`。

## 7. 未运行 / 限制

1. 真实浏览器验收已运行（Chrome + DevTools 协议），但**只在 1680×960**；响应式与 1440/1280/768/390 视口属于第五批。
2. 截图工具需要本机已装 Chrome/Edge；这是本机环境条件，不是页面依赖。
3. 负例（错误 hash、跨版本、缺项、迟到响应、超限/省略）用单测覆盖；页面上没有制造错误引用的样本，因为那需要篡改服务端记录。
4. 客户角色拿不到绑定政策，页面只说明"无法核对"，不显示条款正文；这是服务端权限的结果，前端不绕过。
