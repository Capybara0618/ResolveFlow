# 建议交接：真实Agent整体对照

2026-10-06，按[运行前协议](../../docs/agent-handoff-live-comparison.md)接续[工程改进](../decision-handoff/README.md)。**本轮未证明整体质量提升：同12例旧自动联合11/12，本次10/12；关键阻碍说明更具体，但动作/责任一致性仍不足。**不改旧报告或Gold，不以安全拦截等同有效建议。

## 固定范围与证据

运行前冻结[12例及75输入](../../evals/agent-handoff-live-v1/cohort.json)：旧七项可读性警告＋一项未完成＋四项正向/客户材料对照。代码7e07700，context v13/verifier v7；deepseek-flash，temperature=0、thinking disabled、JSON、输出1024；model_calls=12，其余RunBudget一致。前后观察到的provider别名均deepseek-flash，模型服务版本仍未固定。每例只运行一次，没有失败重试刷分。

本批新增真实60请求；合成资料、真实隔离PG/BGE dense、真实MCP/AgentScope，合成只读HTTP上游。不是Java退款端到端，不启动常驻队列、改业务库、索引或退款。PG评测schema由既有入口创建并清理。生产代码未改，旧v14回放/source hash保持。

- [新逐轮报告](live.json)包含实际system/messages、原模型动作、Observation/引用、usage、轨迹与失败。
- [旧12例投影](baseline-subset.json)只筛原32例的完整entry，重新聚合子集总数；原报告SHA绑定，未改原entry或评分。正式比较直接读原32例并在内存投影，不能拿新12例和旧32例总分相比。
- [来源语义复核](../../evals/agent-handoff-live-v1/review.json)由Codex按原文、全部实际轮次和来源作出，12/12已审；NONBLIND、合成、已见旧结果，不是独立专家或客户准确率。
- [比较与自动重判](comparison-v1.json)复用原评分器，逐条验证政策商家/版本/hash/完整正文和P2；不是调用第二模型或按关键词替代语义判断。
- [最终输入/报告清单](../../evals/agent-handoff-live-v1/manifest.json)与[收口核查](verification.json)保留SHA和失败记录。已有完成报告不覆盖。

## 实际结果

|指标|旧同12例|新12例|
|---|---|---|
|自动动作/联合检查|11/12|10/12|
|有效终局|11|10|
|未完成|1：A15B|2：A02B、A08B|
|被接受的禁止终局|0|0|
|模型请求|64|60|
|provider准确usage|64/64|60/60|
|输入/输出token|110012 / 7782|105391 / 6689|
|案例耗时中位数|11.058秒|13.878秒|
|案例耗时合计|131.565秒|171.393秒|

耗时包含本机、模型和工具，不是整批墙钟或纯模型延迟。请求/用量减少与行动路径、提前失败有关，不能称上下文优化节费；耗时也未改善。用量账本753→813，差值60，limit=null；没有API消费上限、没有把历史reserved_usd当费用。

仅A15B由未完成变为有效建议；A02B/A08B由有效建议变未完成。预算、数据、provider参数与评分器一致，但这是多项Harness变化、模型单次响应的前后观察，非随机试验，不能归因到某一条提示。未自然出现旧CONFLICT错误，不能宣称字段反馈让A15B恢复。

Codex语义维度保留全12分母，2项未完成单列，不拿安全停止充当成功：

|维度|PASS|WARN|NOT_COMPLETED|
|---|---:|---:|---:|
|事实支持|10|0|2|
|政策适用|6|4|2|
|动作与理由|8|2|2|
|补证/核查责任|8|2|2|
|商家可读性|6|4|2|

原usage_audit的independent_semantic_review=PENDING沿用“独立人审”标记；本批Codex复核另在semantic_review及绑定review.json完整保存，没有等待用户人工打标签。PASS不是排版评分：数字/规则编码仍有视觉负担，网页没有在本批调整。

## 问题与取舍

**两条真实纠错均未恢复有效建议。**A02B第5轮说未发货条件不满足，却选择REFUND并列出缺证，收到MISSING_EVIDENCE_ON_REFUND/UNSHIPPED_FACTS_REQUIRED；第6轮再查政策、第7轮补资金，第8轮仍REFUND。A08B第5轮引用失败承运O3被拒；第6轮模型尝试ESCALATE，但finding仍引用O3。两条实际下一轮请求都包含反馈，最终分别STOP/HARNESS/MISSING_EVIDENCE_ON_REFUND与STOP/HARNESS/ACTION_CITATION_INVALID，decision=null，不是12次调用耗尽，也不是有效模型转人工。没有放宽引用、增加第二次修正或伪造模型建议。

**补证动作结构有效不代表责任正确。**A07B与A16B已在summary提到占用/商家责任，但REQUEST_INFO缺项仍是承运结论/人工核验，不是客户可补材料。A14B的照片/包装材料才符合客户补证方向。本次0次ASK_CUSTOMER，3条REQUEST_INFO全部是建议；没有给客户实际发题，明确系统字段的QUESTION门禁只有前批工程证据，不能声称本批真实模型已验证。

**RAG问题必须区分缺来源、错误query与使用错误。**10次SEARCH_POLICY全部实际执行，返回来源及完整正文/P2核对通过；没有新增逐query Gold，不报告“召回10/10”。A02B所需未发货条款已返回，两次终局失败主要是动作/事实不一致。A01B query引入语料不存在的七天无理由，summary把P2错写为未发货规则（实际P1才是）；在途退货/拒收/入库不是本系统实现能力。A14B query含无依据“生鲜”，前三只有未发货/资金/家居材料，漏通用质量条款；补照片建议方向合理，但后续全额退款的条件依据不足。订单category=electronics却用家居材料条款，暴露合成数据的品类一致性缺口，不能只归咎模型。本批不改冻结输入或按案例补词。

**说明改善可见，交付边界保留。**A04B/A12B有效模型ESCALATE明确上游失败及商家下一步；占用案例明确写RESERVED，但责任与条件句仍不完整。有效ESCALATE仅在评测/轨迹保存summary，FAILED协议还未接网页全文；这一轮是直接Runner，没有实测worker回调/网页/退款链。

## 验证与命令

五文件集中83 passed /0 failed/errors/skipped，[JUnit](tests-final.xml)；新增17项涵盖子集不丢失败、标签来源绑定、未完成不得升为PASS、配置/数据/自动分/政策正文篡改。新runner相关Ruff通过。默认严格回放[18/18 MATCH](strict.json)，不是18个新真实模型样本；比较脚本用新tmp输出复算JSON完全相同，0新模型调用。

```powershell
$env:PYTHONIOENCODING='utf-8'
# 以下真实命令已执行；再次运行会新增费用，输出必须新建。
./eval.ps1 -Mode live -Case A01A,A01B,A02B,A04B,A05A,A07B,A08B,A12B,A14B,A15B,A16A,A16B -ModelCalls 12 -Dataset evals/calibrated-v3 -Output reports/agent-handoff-live/live.json -LiveUsage tmp/evaluation-live-budget.json
# 下列只读复算，不调用模型（已完成输出不可覆盖，重现请换新路径）。
agent/.venv/Scripts/python.exe -m scripts.evaluation.handoff_comparison --cohort evals/agent-handoff-live-v1/cohort.json --candidate reports/agent-handoff-live/live.json --baseline reports/rag-delivery/agent-live.json --review evals/agent-handoff-live-v1/review.json --output tmp/agent-handoff-live/comparison-new.json
agent/.venv/Scripts/python.exe -m pytest -q agent/tests/unit/test_handoff_comparison.py agent/tests/unit/test_evaluation_controls.py agent/tests/unit/test_quality_audit.py agent/tests/unit/test_evaluation_review.py agent/tests/unit/test_live_baseline_merge.py --junitxml=tmp/agent-handoff-live/tests-new.xml
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --output tmp/agent-handoff-live/strict-new.json
```

失败记录：预检误用Database为context manager，TypeError，改用psycopg只读select 1后通过，尚未调用模型。初次70项通过，新增真实报告篡改反例后16通过/1失败（测试误写SEARCH_POLICY，wire名为search_policy），纠正测试名保留反例；最终83项通过，原[开发JUnit](runner-dev.xml)/[中间JUnit](tests.xml)保留。Ruff初次2项导入及1项长行，冻结前修复。真实评测退出1对应2未完成，FINISHED/全部分母保留；不能把后续聚合退出0描述为模型质量通过。

未运行新Java/网页/全仓/mypy/故障网络/worker持久恢复或另外20例，旧16类型诊断和8历史失败继续保留。不重做418项前批工程回归，不把前批通过冒充本次重跑。原四脏文件及旧图/日志不夹带。

## 后续顺序

1. 先做通用的动作/说明与责任一致性：把客户材料缺项与商家/系统核查结构化区分；退款条件不成立时反馈可选择的合法方向，保留一次修正与安全停止。用本轮保存坏响应离线重放，加不同表述/状态反例，不写Axx特例，不继续整套付费试错。
2. 补明确失败的商家接管说明：Python→契约→Java→网页纵向连接真实失败原因、已知阻碍及下一步；保持“调查未完成”和“有效模型建议”分开，不能为了好看伪造ESCALATE/PROPOSAL。
3. 再针对query中的无依据限定和政策适用边界评小范围通用方案，先做语义/类别与来源一致性，再决定排序/改写；不凭单题漏召回直接上reranker。最后固定新版本集中真实对照。

本轮先完成证据与原因定位，没有部署新业务功能，未宣布RAG/Agent全部优化完成。
