# 本批入口、样例与测量范围

从仓库根目录使用现有`agent/.venv/Scripts/python.exe`，设置`PYTHONPATH=仓库绝对路径;仓库绝对路径/agent/src`、`PYTHONIOENCODING=utf-8`；PG测试另设`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`。原演示服务可保留；评测业务事实为冻结HTTP，不向Java提交申请。

## 已完成的准备命令

```powershell
python -m scripts.customer_quantification_prepare audit --output 新审计文件.json
python -m scripts.customer_quantification_agent check --output 新预检文件.json
python -m scripts.customer_quantification_rag check
python -m pytest agent/tests/unit/test_customer_quantification_data.py agent/tests/unit/test_support_fixed_current.py agent/tests/unit/test_customer_quantification_metrics.py agent/tests/unit/test_customer_quantification_rag.py agent/tests/integration/test_customer_quantification_runtime.py -q
```

这里`python`代指现有venv解释器，不重选依赖。`freeze`已执行，manifest保存于evals/customer-quantification-v1；源码/数据变化会让check拒绝，不能修改hash迁就。输入生成器只可创建新文件，不覆盖已冻结数据。

## 后续正式执行入口（本轮未执行）

Agent正式命令形态为`python -m scripts.customer_quantification_agent execute --live --max-provider-requests 实际新请求上限 --output 新结果.json`。必须显式live、正上限及新文件，缺任何一项拒绝运行。建议上限800不是本轮已授权额度；32组50轮输入×两组×两次=128会话运行/200客服轮，估计500–700模型请求，最多实际批准值，超限后未完成保留。密钥仍用原用户环境，不写命令或报告。

RAG命令为`python -m scripts.customer_quantification_rag execute --output 新结果.json`，只使用现有本地embedding/CUDA重排，不请求生成API或改业务库；40问×5方案×3轮=600检索请求。质量前3/5直接/父级展开及latency均记录，模型载入预热单列。不把纯检索空标签当正确拒答。

Agent跑完用`python -m scripts.customer_quantification_prepare review-template --runtime 新结果.json --output 新源审.json`产生逐轮待审表。Codex依据来源和实际对话填写pass/evidence，原模板绑定runtime hash、实际run身份和判据；随后`summarize --runtime 新结果.json --review 已完成源审.json --output 新汇总.json`。缺运行/未源审/身份不符/失败被勾通过均明确拒绝。原始结果禁止覆盖，不将程序发布SUCCEEDED等同语义正确。

## 数据样例

- **Q09纠正（两轮）**：客户先称已问代收点没有包裹，再改口尚未开门没问到。通过条件是旧“已询问/已排除”失效，新尚未询问有效，不重复要求已完成的其他排查；物流签收记录不能证明本人已收。
- **Q16插问恢复（三轮）**：先查耳机签收→暂停并问假设在途政策→恢复原问题并准备退款草稿。须保留假设性质、原事项恢复，依据最新ORDER/SHIPMENT/POLICY生成退款摘要而非人工摘要，待客户确认。
- **Q25故障**：本批明确冻结物流503。回答只能说明不可查询，不能因查询失败认定丢失；原业务物流不改。
- **R02多依据**：定制和鲜活商品的七天无理由例外。标注包括总则引导及两类例外，前三子块只找一类不算完整通过；完整性按来源字符区间判。
- **R22冲突条款**：赠品不完整不办理与扣赠品款两处均须保留，不自行用一条覆盖另一条。只测指定冻结政策的证据，不自动采用为本店政策。
- **R33语料外**：某申请是否已到账。静态政策不能回答实时支付结果；不进32题完整依据覆盖分母，保留检索候选，非已测Agent拒答率。

所有新题是来源可见的合成工程验收，语义可能与旧题重叠。业务来源快照复用，非32真实客户/独立事件。普通与复杂分组、所需来源与产物在正式前固定，失败后不补跑换分母。结果不支持提升时保留结果，不能先把简历占位填成期望值。
