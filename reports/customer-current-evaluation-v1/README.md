# 当前版本集中评测

协议见[本批合同](../../docs/customer-current-evaluation-v1.md)，[冻结manifest](../../evals/customer-current-evaluation-v1/manifest.json)。业务实现保持 orchestrated-v1，开发可见合成回归集，不是独立盲测。

## RAG（2026-10-24，已执行）

命令：`agent/.venv/Scripts/python.exe scripts/customer_current_rag.py external` 及 `... runtime`。均退出0，无生成模型调用、无公共库写入。实际运行前后公共PG表hash相等。

外部29题、66片段，沿原文原子证据标签及已缓存向量，17个ANSWERABLE单独作为完整证据分母：

| 召回方式 | Top3 | Top5 |
| --- | --- | --- |
| dense | 10/17 | 13/17 |
| 正文BM25 | 12/17 | 13/17 |
| dense＋正文BM25 RRF | 10/17 | 12/17 |
| dense＋正文BM25＋标题BM25 RRF | 12/17 | 16/17 |

三路Top5为94.1%，相同输入下正文BM25为76.5%，差17.6个百分点；Top3无提升。三路Top5仍漏S:JD03，且相对dense有该题退化。PARTIAL仅1题，Top5三路覆盖其已标注可用证据1/1；不能据此称完整问题可回答。全部29题不能直接作“回答准确率”分母。没有parent扩展/重排，生成答案质量未在此项测量。[原始结果](rag-external.json)。

当前商城 `BoundSources.search`：9查询先各执行一次，再10轮共90次热态，实际只读PG、CPU4线程、原generation。全部走COMPLETE_SMALL_SET，每次返回6规则；必要规则输入覆盖90/90、错误0。该覆盖来自小集合完整输入，不是Top5排序成绩。

- 热态90次：p50 **4.74ms**，p95 **5.84ms**。
- 进程本地embedding＋词法预热 **7589.5ms**，单独计，不计入热态检索；商城小集合搜索本身跳过embedding。
- 预热后首实际查询 **19.09ms**，其余首遍查询约4.1–4.8ms；不称为冷启动总耗时。
- 仅工具内部查询到证据，不含Agent理解/调查/生成、Java/SSE或浏览器耗时。[原始计时](rag-runtime.json)。

## Agent

真实44轮尚未运行；不能引用此前单例代替本批结果。计量驱动已通过5单元＋1临时PG录制集成＋3原编排集成，共9过0跳过，Ruff通过。零付费[预检](preflight.json)核实两租户索引精确generation，源码/输入/权重hash已冻结。
