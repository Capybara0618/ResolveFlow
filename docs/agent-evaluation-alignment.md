# Agent / RAG 第一批：输入与评分校准

2026-10-05 用户授权实施。范围为校准评测、修正记录、定位上下文溢出；不改变提示词、检索算法、模型配置、资金权限，不新增收费模型调用。

## 输入以已实现的业务协议为准

Case 在派发时通过 `ReviewerRunInput.snapshot` 给出当前 revision 的 `review_context`：原始诉求、客户材料/回答、人工核验结论、已有问题及来源版本/hash。Python `RunRequest` 验证材料属于本次派发且没有未来 revision，worker 传给 `RunFacts`。

`get_case_evidence` 的真实 Java 返回只有 `case_id`、`input_revision`、`evidence`。列表的每项只有材料 ID 和来源三元组，不再次返回材料正文。材料 ID 不等于外层工具 Observation ID；提出建议仍须引用本 run 实际读到的外层 Observation。评测按这一协议接线，不能为方便脚本修改后端接口。

v1 漏传派发快照，又把正文放进材料查询结果。它的执行结果保留为旧协议基线，不能用它判断当前真实业务质量。

## 新版本与 Gold 变更

`evals/current` 的 v1 文件、hash、旧报告原样保留；另建 `evals/aligned-v2`，manifest 记录父版本 hash 和变更。32 案例/16 对、dev/test 划分、允许/禁止动作、政策文本、60 RAG 查询及规则 Gold 沿用原版。客户回答归为真实协议的 `CUSTOMER_STATEMENT`，通过 `question_id` 关联已有问题；人工核验仍为 `REVIEWER_VERIFICATION`。材料 ID 为固定合成 UUID，revision 按追加顺序递增。材料 hash 是合成正文 SHA-256，与引用绑定；不是宣称复现 Java 对真实提交记录的 canonical hash。

Gold 不规定调用顺序。质量退款的“送达”事实可由订单可信履约投影或物流查询证明，移除重复查物流的硬性要求。未发货退款仍须明确未发货与履约版本；运输丢失仍须物流明确丢失；已发货退款须材料快照中的人工确认与材料查询返回的来源精确匹配。读取工具但缺事实值、引用 hash 错误、旧核验被新结论取代都不能满足支持条件。保留动作、政策引用、资金状态检查，不为了让旧答案通过而改允许动作。

`support_requirements` 只在 Gold 内，禁止进入模型输入。自动检查覆盖结构与事实支持，不代替解释语义、问题合理性或专家人工复核；Gold 仍是合成并经代码政策核对，未有人类独立签审。

## 记录与溢出定位

检索轨迹的 `hits` 从本次实际 Observation 的候选列表计数，包含持久记录复用路径；不根据未赋值的临时变量计数。此次没有改变候选排序或查询。

每个实际模型请求记录上下文估算、上限与层级。溢出时记录 cap、累计剩余预算、provider capacity、输出预留、P0/P1/P2 的字节贡献和各 section 大小；只记录大小和标签，不在诊断重复材料正文。估算函数当前按 UTF-8 字节保守计数，必须与真实模型 tokenizer / 账单 token 区分。强制内容超限仍停止，不删约束或放大预算。

生产代码变化会改变 Harness manifest。因此五个当前回放包在新版本中重新由隔离 PG 的 SDK 持久运行导出，旧包保留；strict 回放的 manifest、缺记录和篡改检查不放宽，不替日常旧 run 换 manifest。

## 执行与验收

默认 `./Eval.ps1 -Mode validate` 使用 aligned-v2；历史版本显式传 `-Dataset evals/current`。所有执行与离线重判必须使用对应数据版本，v1/v2 不进行效果提升对比。新报告写到 `reports/agent-alignment-batch1`，不能覆盖旧报告。

本批集中验证输入隔离/来源绑定/评分失败路径、真实 MCP 协议、SDK 上下文/检索轨迹、持久恢复/fence/strict 回放及 Java 快照/材料接口。再跑 32 个实际 SDK＋MCP＋embedding 的合成脚本案例，分析溢出大小；这些调用不是 LLM 效果评测。不重算日常 run，不清业务数据，不自动启动第二批。

后续第二批才按本批证据调整上下文表达；调查策略与终止、RAG 召回、有限 Live 效果对比各自单独实施。当前真实检索的 Q48/Q49 漏召回不在本批修复。
