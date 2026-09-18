# 政策检索 · v1.2核心

目标是可靠定位适用政策并给出可验证引用，不是比较所有RAG组件。Java结构化规则负责资格/授权；检索相似度不决定是否退款。

## 1. 政策

Case保存不可变bundle：merchant/category、version、[effective_from,effective_to)、published_at、status、rules_json、正文hash。政策由受控种子/导入脚本加载并校验，不开发全套管理后台。

按订单paid_at选择当时已发布且生效的版本；被撤销的政策不自动授权，也不静默套新版。即使只用合成政策，也要测时间边界与跨商家过滤。所有政策标SYNTHETIC_DEMO_POLICY。

核心规则：物流确认丢失可REFUND，损坏/签收争议必须人工。缺失、多条冲突或正文与结构化规则不一致都阻止自动执行。金额阈值固定配置并版本化；授权消费时重新校验当前规则。

## 2. 核心检索

规则小节分块，保留rule_id/bundle/version/hash与条件例外，禁止把例外切掉。先按merchant/category/manifest/bundle/version硬过滤，再做真实embedding的dense cosine检索，top_k<=5。

PG/pgvector精确扫描足够用于核心小语料，不启用HNSW。BM25作为离线基线而非默认第二路在线召回；hybrid、RRF、rerank退出必做。

沿用原选择的本地中文embedding候选及T00已锁Python依赖，C07实测可用模型并固定revision/维度/许可与资源开销，不伪造embedding。资源/下载受限时先用fixture测试流程，真实检索结果仍需实际embedding实验；模型替换须记录理由与新的manifest，不重开整栈。

## 3. 同步与引用

先拉指定不可变bundle→构建generation→校验hash/维度→标READY。run绑定READY索引，未就绪可重试等待至deadline或转人工，不静默搜旧政策。核心不做第二条“降级检索成功”路径。

policy_refs含bundle_id/version/rule_id/chunk_id/content_hash。Python检查是实际返回过的引用，Java按原规则复核。禁止将政策正文里的指令当系统权限。

## 4. 最小证据

至少20个规则段落，2商家、2历史版本，含近似文本/时间边界/例外。40条查询，20dev/20冻结test，按语义家族分离。

对照BM25与dense，报告Recall@5、版本/商家正确性、查询耗时与错误。样本小不写广泛泛化结论；dense不优于BM25也如实报告。不要求四组消融，不把无数据的“检索提升”写进简历。
