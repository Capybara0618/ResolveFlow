# 第五批固定版本真实质量基线

2026-10-05，用户批准接续RAG；[规格](../../docs/agent-quality-batch5.md)。完成32例真实模型一次性基线、11个外部FAQ来源、本轮33条真实搜索决策的离线探针、审计与待人审队列。**质量未全通过，不宣称Agent/RAG优化全部完成**。

## 实测结果

生产源码保持a073f32全部字节不变，context v10 / verifier v5 / 正文dense。真实模型使用DeepSeek的`deepseek-flash`别名，temperature=0、JSON mode、thinking disabled，供应商模型快照没有锁定。业务输入/政策是aligned-v2合成数据，真实SDK/MCP、隔离PG和固定本地embedding；没有Java审批/退款/业务写入或消费日常队列。

| 指标 | 结果 | 含义 |
| --- | ---: | --- |
| 选择/完成运行 | 32/32 | 每例一次，失败未筛除/重跑 |
| 有终局建议 | 25/32 | 7例安全停止不算完成 |
| 自动动作符合Gold | 25/32 | 合成Gold，不是独立语义正确率 |
| 自动动作＋依据联合通过 | 22/32 | 读取、引用和有限事实支持检查 |
| 被接受的禁止终局动作 | 0 | 不代表模型未提出错误动作或任意幻觉均能识别 |
| 拒绝通知 | 21 | 错误/纠正过程均保留 |
| 请求/供应商usage | 156/156 | 输入252623 token、输出18031 token，无估算usage混入 |
| 独立语义人审 | 0/32 | 全部PENDING |

每例评测6次调用、输入配置8192/预留输出1024（构造cap7168）、输出1024；生产默认12次调用，不能等同生产成功率。本次7个停止不是累计额度或BUDGET_MODEL_CALLS：6次CONTEXT_REQUIRED_OVERFLOW、1次ACTION_REFUSED。ledger96→252/limit=null；历史预留$0.2855712未更新，不是本次费用或账单。

[全部请求/决策/usage/Observation](live-all.json)、[最终审计](audit-verified.json)、[32例表](cases.md)、[冻结/用量/公开库核查](receipt.json)。audit.json为增加计量比例前的审计，保留过程记录，最终用audit-verified。quality_audit.py是在模型请求后新增的只读分析器，自己的hash另存，不冒称在请求前存在；Agent生产文件的前后全量hash逐字相同。

## 失败归因（执行者分析，非独立专家审查）

1. **上下文计量/必保内容是当前明显瓶颈。** A01B/A02B/A05A/A07A/A11B/A12B构造下一轮时超过7168的估计cap。六例最后已发送请求字节估计6883–7097，供应商输入token1861–1992；这是保守计量的实测信号，不能混用字节与token。超限下一轮未发送，实际token没有测得。全部156请求的最大供应商输入是1992，不能据此声称模型窗口被撑满。
2. **缺终局引用不等于RAG漏召回。** A05A实际成功检索含R-LOST-001（第1），A07A含该规则（第3）；随后补读承运轨迹，下一轮构造超限。没有终局引用导致评分missing_rules，但不能归为RAG漏召回。A01B泛查退款后再查已发货在途，两次各top3增加必保政策；首次错误拒绝建议被Harness拦住。
3. **四个输入违反现行core读取契约。** A03B/A07B/A16B把UNKNOWN填进line_refund_state，而LineRefundState只允许FREE/RESERVED/CONSUMED；A03B的退款slot读取state也为UNKNOWN。UNKNOWN属于退款操作状态，不能混作slot。A04B的paid_at/payment_version为null，不符合LineContext类型。真实Java来源须另校准，不能放宽validator让合成样本过关。前三例最终安全补证/转人工，但Gold要求成功get_order_context，联合分数不通过。保持32分母及原Gold，不静默重新计分。
4. **引用/协议修复有真实失败。** A04B读取失败后引用不存在的O2；修复阶段最后输出非法包装且索要已绑定订单号，以ACTION_REFUSED停止。不是网络错误，不能称纠错保证自愈。

后续优先：新profile校准合法Java状态与坏数据反例（不覆盖v2）→按实际计量处理保守误差/无损去重，保留来源/冲突/政策例外→重测失败→逐query独立Gold后判断检索。当前不支持直接堆混合召回/reranker解决这些终止问题。

## 外部问法与本轮query

一手来源如[京东签收争议FAQ](https://help.jd.com/user/issue/108-385.html)，[11条逐页来源/短问题/hash](../../evals/external-faq-v1/sources.json)。FAQ由平台编写，部分页面为历史帮助，只取问题、不导入其回答为项目商家政策。11个问法跨3家v2政策形成33个范围诊断，不算33个独立样本；排名前固定、便利取样，非真实分布/盲测。

[JDDC论文](https://arxiv.org/abs/1911.09969)描述真实客服语料，但[JDDC 2.1作者入口](https://github.com/hrlinlp/jddc2.1)要求申请，本批没有获得或使用真实客服记录。用户无额外样本，不用更多自写题冒充独立数据。

本轮提取33个SEARCH_POLICY决策，保留原query、case/轮次、商家/bundle、原top_k、请求失败标记和来源hash。离线统一top5不冒称线上top5，搜索决策也不自动证明工具执行，实际Observation另查live-all。

[候选探针](query-probes.json)：(33外部范围问题＋33模型query)×dense/BM25共132结果，0检索错误/0主体、版本或manifest违规；**未逐query标注、所有准确率null，不计算召回率或选赢家**。正文dense前2平均字数为外部225.45/live223.45，不是token或完整上下文大小。返回相似候选不等于适用或退款授权。

[逐query待标注](query-review-pending.json)66行及6份完整项目政策，must_rules均null；人工确认无适用规则后才能填空数组。先看问题/原条款再看排名，不抄工单终局Gold。该文件尚未接正式人审/准确率评分入口，待独立Gold冻结后实现。

[建议语义模板](semantic-review-pending.json)/[待审评分](semantic-score-pending.json)绑定报告hash，32/32待审，人审门禁正确返回1；只有具名人审才能补支持性、幻觉与追问相关性。本执行者未填人审通过。

## 工程验证与未运行

- 13相关模块223 passed/0 skipped：[输出](pytest.txt)/[JUnit](tests.xml)；只读审计6 passed：[最终输出](audit-tests-verified.txt)/[JUnit](audit-tests-verified.xml)。合计229不同项，重复运行不叠加。
- 分母缩水/重复独立来源反例首次2 failed/13 passed，修正后15 passed（已含在223）：[失败](probe-before.txt)/[修正](probe-fixed.txt)。Ruff首次一个121字符行失败，换行后最终4文件通过：[结果](ruff-verified.txt)。没有删断言。
- 冻结v1/v2、Harness28/28、rag-v8 strict13/13通过；生产源码不变，不新建或覆盖回放。[完整命令/退出码](commands.json)保留真实质量未全通过及人审PENDING的退出1。曾查错文件路径、首次文档patch锚点失败，无生产变更。
- 入库差异检查发现PowerShell捕获的txt使用CRLF；统一LF并去行尾空白，原txt保留tmp/batch5-original-logs。真实JSON请求/响应/usage、来源hash与冻结数据字节不改，规范化后差异/链接/hash/密钥检查通过。
- public仍4COMPLETED/15模型/10工具/8回调；前后计数和冻结manifest不变，无测试schema/ledger锁残留：[之前](state-before.json)/[之后](state-after.json)。
- 未运行独立Gold/语义人审、真实用户分布、Java整链/浏览器/部署/日常队列、新RAG算法、全项目mypy；上一批16项/9文件既有类型错误仍保留，不宣称全项目门禁通过。依赖/旧Gold/旧报告不改。

复现会产生新真实调用，使用原ledger及新输出路径：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
$caseIds=(Get-Content evals/aligned-v2/agent/cases.json -Raw | ConvertFrom-Json).id
.\eval.ps1 -Mode live -Case $caseIds -Dataset evals/aligned-v2 -LiveUsage tmp/evaluation-live-budget.json -Output tmp/live-new.json
agent/.venv/Scripts/python.exe scripts/evaluation/quality_audit.py --input-report tmp/live-new.json --output tmp/audit-new.json
agent/.venv/Scripts/python.exe scripts/evaluation/rag_probes.py --live-report tmp/live-new.json --output tmp/probes-new.json --review-output tmp/query-review-new.json
```

进度只在todo顶部，四历史脏文件和草图日志不提交。commit/push SHA与远端确认见收口回复。
