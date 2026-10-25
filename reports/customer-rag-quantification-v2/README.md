# RAG量化v2：固定Query、正分融合与完整证据包

2026-10-25，用户冻结Agent文案后进入RAG测量。[协议](../../docs/customer-rag-quantification-v2.md)保持原4文档/66子块/40问题与标签，主对照BM25-direct，预定候选正分RRF-parent，强对照BM25-parent。六路、每路120次，共720本地请求，不新增生成模型API、不改生产/旧成绩。资料已见，用于回归与机制消融，不能称新独立验收集。

固定每路20候选、3/5锚点、正文8000字符且4096tokens。主质量是最终证据包找齐必要依据的题数/32，直接子块命中与父级展开分开，8语料外不算拒答准确率。计时只含Query到Top3入口证据包的实际流水线，Top5和标签评分在计时外；模型加载/预热另列。旧600计时组装两份包，不能直接宣称本轮比旧结果快了多少倍。

已实现[scripts/customer_rag_quantification_v2.py](../../scripts/customer_rag_quantification_v2.py)与7项新检查；结合原来源组装9项，共16通过，两文件Ruff通过。先缺模块收集失败，接通实际表格来源后发现通用catalog没有kind/rows，旧组装器无法识别table_row；新适配器按原v4做法从同一冻结原文恢复这些渲染元数据，并验证正文/hash完全相同，没有改块、标签或表格内容。初次Ruff循环lambda绑定两项已修正。

离线检查覆盖：词法零分不投票、dense不加阈值、选择输入不含Gold、六路真实来源范围/锚点保留与预算、独立题分母和真实均值、缺矩阵/重复/非有限时延拒绝。脚本编码只是接线检查，不是模型质量；正式检索结果在新manifest核验后执行一次。业务补充使用最近实际Agent政策Query，只读原PG/固定generation，核对与当时实际返回相同；不替代外部长文主实验。

命令（仓库根，PYTHONPATH为仓库与agent/src）：

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_rag_quantification_v2 freeze
agent/.venv/Scripts/python.exe -m scripts.customer_rag_quantification_v2 check
agent/.venv/Scripts/python.exe -m scripts.customer_rag_quantification_v2 execute --output reports/customer-rag-quantification-v2/results.json
agent/.venv/Scripts/python.exe -m scripts.customer_rag_quantification_v2 business --output reports/customer-rag-quantification-v2/business.json
```

输出拒绝覆盖；后续当前状态只看tasks/todo.md顶部。Agent文案单独冻结于[确认稿](../../docs/resume-agent-frozen-20261025.md)，不因检索实验顺带改写。
