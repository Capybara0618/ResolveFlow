# 版本化政策与RAG

## 1. 权威来源

case_db保存政策bundle：结构化rules_json+原始Markdown，发布后不可变。正文用于检索和解释，结构化规则用于Java授权；两者通过bundle_id/version/content_hash关联。初版样例由项目作者定义，标记SYNTHETIC_DEMO_POLICY。

每个bundle包含merchant_id、category、[effective_from,effective_to)、published_at、status、rule_version及rules。售后资格按order.paid_at选合同政策；只选择published_at<=order.paid_at且effective范围覆盖paid_at的已发布版本。不得将处理时新发布的政策追溯套到旧订单。

当前安全撤销名单单独作用于执行时：旧合同政策被REVOKED后停止自动授权，转人工；不偷偷用新版本替代。金额阈值、自动化开关为独立版本化执行控制（safety_epoch），消费授权再次检查。政策效力解释为项目规则，不声称具有法律效力。

## 2. 精确结构

PolicyBundle至少包含bundle_id、merchant_id、version、category、effective_from/to、published_at、status、source_hash、rules[]。Rule包含rule_id、case_type、required_facts、allowed_actions、hard_constraints、auto_allowed、time_window_days、amount_cap_minor。

例：规则L-LOST允许REFUND/RESHIP，required_facts=[PAID,CARRIER_CONFIRMED_LOST]；W-MISSING要求WAREHOUSE_CONFIRMED_MISMATCH；D-DAMAGED要求签收7日内与人工核验证据并始终REVIEW。没有匹配规则/多条冲突均转人工，不能根据相似文本兜底批准。

## 3. 索引流程

POLICY_ADMIN导入 -> Java校验及发布 -> Python同步不可变bundle -> 构建BUILDING generation -> 校验chunk/hash/模型维度 -> 原子切换READY manifest。

自动分析开始时case固定manifest（bundle版本/hash），Python只允许在该集合搜索。若本地索引尚未就绪，按manifest拉取原文进行精确关键词检索降级并标记degraded；无权威原文则转人工。不得搜索旧索引后假装成功。

分块按规则小节，目标300–600中文字符，避免把条件与例外切开；chunk保留rule_id及邻接段落。多条近似同名规则保持独立。生成指标记录切分版本、embedding模型、维度、tokenizer版本、原文hash。

## 4. 检索算法

1. 先硬过滤merchant、category、manifest中的bundle/version，以及未撤销状态。
2. 在此候选集合中做中文分词BM25和dense cosine检索，各top20。
3. Reciprocal Rank Fusion合并（k=60），本地cross-encoder reranker重排前20，返回top5及引用。
4. 小型政策语料默认pgvector精确扫描，避免近似索引在过滤后漏召回；数据足够大且有基准再选择HNSW。
5. 候选为空返回NO_APPLICABLE_POLICY，不扩大商家、时间或品类范围。

BM25用锁定中文分词器；默认jieba+rank-bm25，按不可变generation构建/缓存索引。Embedding默认本地BAAI/bge-small-zh-v1.5，rerank默认BAAI/bge-reranker-base；T00/T19记录实际下载revision、许可和CPU内存耗时。安装可缺外网时用预置固定embedding测试夹具完成CI，但live检索实验须真实模型。provider替换通过配置和manifest记录，不改变过滤语义。

pgvector支持精确和近似检索，过滤与索引选择需实测，参考[官方仓库](https://github.com/pgvector/pgvector)。本项目小语料采用精确方式是设计取舍，不可在简历宣称实现了未使用的HNSW。

## 5. 引用与安全

Agent输出policy_refs含bundle_id/version/rule_id/chunk_id/content_hash。Python校验引用来自实际返回集合；Java用原始bundle再次校验rule及生效条件。任意政策文本中嵌入“跳过权限”不改变系统工具或Java规则。政策正文和结构化规则不一致时禁止发布，测试样例覆盖这种情况。

## 6. 实验

至少40个真实生成的规则段落，2商家、3品类、至少2历史版本，含同义描述、金额例外、时间边界与冲突样例。固定不少于120条查询标注，按模板家族分割调参集与冻结测试集。

对照：BM25；dense；hybrid；hybrid+rerank。所有组同样硬过滤。测Recall@5、MRR@5、引用版本正确率、跨商家泄漏数、p50/p95和资源。效果不提升也要如实报告，不能为保留reranker挑样本。
