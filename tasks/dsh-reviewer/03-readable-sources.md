# 第三批：政策和工具依据可读

先读[总约束](README.md)。依赖第二批稳定mock样本；目标是让审核员能从建议定位准确原文，理解条件与例外。引用全匹配和来源投影已实现，不能推倒重做。

## 1. 源码入口和改动范围

| 入口 | 本批用途 |
| --- | --- |
| `web/src/ui/InvestigationSources.vue` | 已读取investigation并保留省略/错误提示；扩展工具特定摘要 |
| `web/src/ui/InvestigationFindings.vue` | 已分FACT/INFERENCE/CONFLICT；核对材料引用匹配和跳转 |
| `web/src/ui/ReviewerWorkspace.vue` | 已读review-context的绑定政策；复用同一份条款内容 |
| `web/src/App.vue`、`web/src/client.ts` | 建议引用按钮、状态同步、类型及请求复用 |
| Case的 `ReviewerInvestigationService.java`、`ReviewerWorkspaceService.java` | 当前revision/主体绑定投影；仅发现缺口才修改 |
| `agent/tests/integration/test_reviewer_sources.py` | 主体、run/revision和限额回归 |
| `web/tests/investigation-sources.spec.ts`、`investigation-findings.spec.ts`、`reviewer-workspace.spec.ts` | 现有前端回归入口 |

新增展示组件/纯格式化模块可使用 `web/src/ui/PolicyCitation.vue`、`web/src/ui/investigation-format.ts`（新文件，按实际需要创建）。不新建政策管理后台或历史run查询API。

## 2. 子步A：引用与原文定位

1. 统一政策引用键：`bundle_id/version/rule_id/chunk_id/content_hash` 五项全部相等。证据键是 `observation_id/source_ref/source_version/content_hash` 四项全部相等。缺任一关键字段，不视为已核对。
2. 政策优先从现有review-context的 `policy_rules` 获取：PolicyText已包含五项键、title、text。复用当前请求结果；组件间通过props/共享父层数据传递，不每个引用发一次网络请求。
3. 点击建议引用打开或展开对应条款，滚动并将键盘焦点移到可读标题；标题是条款名，版本信息放次行。不要只跳转到通用政策列表，也不要仅用rule_id匹配。
4. 五项不匹配显示“该引用未能匹配当前绑定政策”，保留引用元信息。不静默退到最新政策/同名规则，不展示错误原文。
5. 核对 `InvestigationFindings.vue` 的source函数：当前材料分支仅按observation_id找到材料，需要与proposal.evidence_refs中的完整引用核对，防止旧方案匹配上新内容；如历史缺引用，明确不可核对。工具分支现有完整匹配应保留。
6. 旧方案可读但明确失效；其引用若不在当前调查记录里，显示未提供，不借用当前revision来源。不要在本批新增历史revision选择器。

必要测试：五项政策键逐项改变都不能定位；证据同ID不同version/hash不可标“已关联”；同名跨商户/版本条款不串；正确引用能展开、定位；切换工单时迟到请求不串内容。

## 3. 子步B：从已保存结果提取业务摘要

以第二批真实保存的observation.result结构为依据，不从记忆猜字段，不读取实时业务接口填历史空白。用类型守卫处理unknown；格式化不能修改原始JSON。

| 工具 | 默认摘要 | 限制 |
| --- | --- | --- |
| get_order_line | 订单/行号、商品或SKU、数量、实付、支付时间与状态（实际存在才显示） | 整数分使用现有money.ts；0不是缺失，null不是0 |
| get_shipment_trace | 记录状态、承运商结论、关键事件时间、签收/丢失冲突 | 不把SIGNED解释成客户认可收到；事件分页不假装完整 |
| get_case_evidence | 材料来源、提交内容、人工核验及理由 | 客户描述与人工核验分项，未核验不能画绿勾 |
| search_policy | 命中标题、bundle/version、片段及检索相关性 | score是相关性，不是退款资格或模型置信度 |
| read_policy | 完整条款、版本、适用条件与例外所在原文 | 原文没有结构化字段就展示原文，不猜条件 |

摘要默认展示少量关键项，完整原始结果继续可展开；长文本自动换行，不把JSON铺满主建议区。未识别的工具保留原文和来源信息，不能抛错导致整页空白。

所有现有提示必须保留：NOT_SCHEDULED、UNAVAILABLE、空观察、error_code、body_omitted（超过32768 UTF-8字节）、truncated（最多40条）、model_provider缺失、mock标签。省略内容不能由摘要或Agent文本补造。

## 4. 子步C：条件、例外和校验分层

条款展示保持三层：原始条款（权威文本）→ Agent解释/适用判断（明确标注）→ Java复核结果（仅现有服务端结果）。没有结构化Java规则项就显示当前方案status/refusal_reason，不新增前端资格计算器。

政策原文已有“条件”“例外”等字段则按契约渲染；只有连续文本时可按原文段落显示、突出原文确有的“且/除外/但”等片段，保留上下文，不能通过关键词匹配推断法律/业务结论，也不调用模型生成“权威摘要”。不扩大本批为政策schema重建。

引用跳转失败或Agent源服务断开时，只在依据区显示错误；客户材料、已保存方案、允许的人工操作仍可读取。提交动作继续由服务端判定资格，客户端缺少政策内容时不伪造可选引用。

## 5. 集中验收

在lost-review、signed-conflict、damage-review样本核对：点击引用到正确版本；例外完整可见；事实和推断分开；模拟来源故障能继续查看已有材料。另用测试覆盖错误hash/版本、跨商户404、切换工单迟到响应、超限/省略、未知来源。

```powershell
pnpm --dir web test
pnpm --dir web build
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am '-Dtest=ReviewerInvestigationServiceTest,PolicyApiTest,ManualProposalApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_reviewer_sources.py -q
```

Java/Python仅当涉及其代码/契约或首次需补接口隔离证据时运行；纯前端之后不重复其未变测试。改协议时追加总手册的契约检查。

交付 `reports/reviewer-readable-sources.md`：样本ID、引用五项示例、实际点击结果/截图、错误关联负例、故障降级、命令及数量。截图须来自正式页面真实接口，不能用preview替代。记录完成后提交并进入第四批。
