# 七条简历量化：RAG实测

2026-10-07，本机CPU实测，来源标签沿用CODEX_REVIEW。正式结果：[外部五组](external-v2.json)、[商城补充](mall-v1.json)。这是本轮新测量，未修改旧语料、Gold或报告。

## 外部原始政策

同一66个BODY检索子块、29条原查询，17条完整可答计入质量分母。每组5次预热、29条各3轮计时，共435次正式在线检索；18条改写各组一次，共90次附加检索，质量与耗时另报。部分可答1条、需澄清3条、语料外8条保留逐query记录，不算完整回答。查询编码、过滤、排名、融合、reranker分词及推理计入耗时；不含模型加载、文档索引、父章节展开。

| 组 | Recall@3 | 完整依据@3 | MRR@3 | 完整依据@5 | 平均ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| A BM25 | 81.37% | 12/17 | 0.7745 | 13/17 | 7.26 | 17.00 |
| B dense | 71.08% | 10/17 | 0.6078 | 13/17 | 9.98 | 14.60 |
| C BM25→rerank | 85.78% | 13/17 | 0.9020 | 17/17 | 2219.45 | 3437.09 |
| D BM25+dense→RRF | 73.04% | 10/17 | 0.7549 | 12/17 | 16.39 | 27.73 |
| E hybrid/RRF→rerank | 85.78% | 13/17 | 0.9020 | 17/17 | 2240.43 | 3486.82 |

C与E在原查询及改写上的质量完全相同。按约定选择C：少一次dense/RRF，延迟略低。相对BM25，Recall@3提升4.41个百分点，完整依据命中率提升5.88个百分点；相对dense分别提升14.71和17.65个百分点。C的Recall@5为100%，MRR@5为0.9137。CPU重排成本约2.22秒，不能写成同时提升检索速度。

Recall对等价充分依据集合取最大完整原子项覆盖比例；完整命中必须覆盖一个充分集合全部原子项。MRR使用能完整覆盖任一原子依据的首个检索子块，@3/@5为截断值，完整排名MRR另保存在逐query的mrr_full。父章节展开单独记录：C前三展开完整16/17；不能将该值替代子块直接13/17。

18条改写中12条完整可答，C/E前三完整8/12、Recall@3 82.64%，前五仍8/12。原查询前五17/17不代表改写同样全覆盖。

## 商城政策补充

同一calibrated-v3政策与60查询，54条有必需规则、6条无必需规则。质量测一次，每组60条×3轮计时，两个候选共360次；均先预热5次。实际PG隔离schema、存储规则向量及生产pin/merchant/generation校验；实验重排适配器不替换生产默认检索。

| 组 | Recall@3 | 完整依据@3 | 完整依据@5 | 平均ms | p95 ms |
| --- | --- | --- | --- | --- | --- |
| 当前dense | 93.52% | 49/54 | 52/54 | 12.84 | 15.78 |
| BM25→rerank | 98.15% | 52/54 | 52/54 | 546.03 | 592.60 |

业务选择C，供固定与动态Agent共同使用。Recall@3提升4.63个百分点，完整依据命中提升5.56个百分点，前五无额外提升。小商城政策重排平均约0.55秒；与外部原文候选长度/数量不同，耗时分别报告。

## 配置、验证与中断记录

- Windows、本机AMD Ryzen 9 8940HX（16核/32逻辑线程）、物理内存16425455616字节；PyTorch 2.14.0+cpu，计算4线程/inter-op 1线程，CPU FP32。BGE-small-zh-v1.5 revision 7999e1d3359715c523056ef9478215996d62a620；BGE-reranker-base snapshot 2cfc18c9415c912f9d8155881c133215df768a70，batch8、max_length512；重排输入逐次检查，无截断。RRF每路前20、k=60；父展开8000字符。
- 实际命令：`agent/.venv/Scripts/python.exe scripts/resume_rag_benchmark.py --reranker <本地snapshot> --output reports/resume-quantification-v1/rag/external-v2.json`；`agent/.venv/Scripts/python.exe scripts/resume_mall_rag.py --variant C --reranker <同snapshot> --output reports/resume-quantification-v1/rag/mall-v1.json`。离线缓存加载，无新模型下载/聊天API调用；商城临时PG schema按已有environment清理，不清业务库。
- 外部2项计量单测通过、相关Ruff通过；商城实际完成360次检索和120条质量记录，未出现异常。外部正式235条质量记录/525条计时记录（原435、附90），源码与输入在运行前后核验SHA。
- [external-v1.json](external-v1.json)及[最后未替换的检查点](external-v1-aborted-checkpoint.json)保留首次中断：Windows文件占用导致WinError5，本地保存失败。只修本地保存重试，完整重新预热/测量另存v2；中断尝试不当成完成成绩，不改原始记录。
