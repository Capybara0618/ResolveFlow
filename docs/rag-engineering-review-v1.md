# RAG Query、检索工程与业务知识质量审查

2026-10-20。用户要求阅读成熟GitHub系统，区分Query生成、检索设计与文档质量问题。本文记录已读代码行为及本项目建议；不是已实施优化或效果提升报告。当前进度只看[todo顶部](../tasks/todo.md)。

## 阅读范围与版本

源码原文件只读下载在忽略目录`tmp/rag-engineering-review-v1/`，未安装、运行或复制进生产。公开[来源清单](../reports/rag-engineering-review-v1/sources.json)保存固定revision、路径和SHA-256。

| 系统 | 本次固定版本 | 定点阅读 |
| --- | --- | --- |
| RAGFlow | v0.23.0，`8dc5b4dc56c18497a16d8ca91b2abf9bdf9dd8a0` | dialog_service、generator、query、search |
| Dify | main快照`88529a0dcdda7ec680384915782bf14fa217da9b` | dataset_retrieval、retrieval_service |
| Haystack | main快照`e4d2e4d95d80cf18a8b18d8e5b8d63296aad119f` | QueryExpander、MultiQueryTextRetriever、DocumentJoiner |

GitHub API初次请求403 rate limit，改用`git ls-remote`固定revision及raw读取。RAGFlow所见main快照的上述三条旧路径404，改为明确指定v0.23.0标签，并补读该版本generator；不把它描述为已读最新main实现。来源清单保留失败记录，不从失败页面推断功能。总计9份成功源码，确认的是所读模块与配置分支，未做完整部署或性能对比。

## 1. Query如何处理

### RAGFlow：多轮补全、关键词增强是可选步骤

[dialog_service](https://github.com/infiniflow/ragflow/blob/8dc5b4dc56c18497a16d8ca91b2abf9bdf9dd8a0/api/db/services/dialog_service.py)在多轮且`refine_multiturn`开启时调用`full_question`；[generator.full_question](https://github.com/infiniflow/ragflow/blob/8dc5b4dc56c18497a16d8ca91b2abf9bdf9dd8a0/rag/prompts/generator.py)把客户/助手历史组织为完整问题，模型报告错误时回到最后输入。跨语言处理、关键词提取分别受配置控制，并非每次必跑。指代补全有明确入口和计时点，不能等同把所有历史无区别拼入关键词。

项目启发：保留原始问题；把当前诉求、有效历史、工具事实组织成可独立检索的问题。特别验证“没收到/已经收到”“未知/确认丢失”的区别。是否额外模型改写须测效果/费用，第一轮可先改进现有Agent的SEARCH_POLICY生成方式。

### Haystack：有边界的扩展，并保留原查询

[QueryExpander](https://github.com/deepset-ai/haystack/blob/e4d2e4d95d80cf18a8b18d8e5b8d63296aad119f/haystack/components/query/query_expander.py)提示同意图的词语/表达变体，输出结构化查询数组；扩展数可控、去重，默认`include_original_query=true`，扩展失败时可返回原查询。开关关闭时失败可能为空，不能笼统宣称总有原查询。[MultiQueryTextRetriever](https://github.com/deepset-ai/haystack/blob/e4d2e4d95d80cf18a8b18d8e5b8d63296aad119f/haystack/components/retrievers/multi_query_text_retriever.py)并发执行多查询，合并、去重并排序。

项目启发：扩展是表达变化，不能凭空新增用户诉求。本次失败Query的“补发”没有来自用户请求，应作为漂移审查项；但尚未证明删除它单独能修复排名。现阶段不默认多次LLM/多查询，先比较保真单查询与原查询。

### Dify：查询来源与检索节点分别配置

所读[dataset_retrieval](https://github.com/langgenius/dify/blob/88529a0dcdda7ec680384915782bf14fa217da9b/api/core/rag/retrieval/dataset_retrieval.py)接收query、数据集和过滤配置，再调检索服务。不能据这个检索模块声称Dify一定先自动改写每个客户问题。可借鉴的是查询生成与检索参数独立组织和诊断。

## 2. 检索如何组织

**RAGFlow：多字段匹配、向量召回及后续排序。** [query.FulltextQueryer](https://github.com/infiniflow/ragflow/blob/8dc5b4dc56c18497a16d8ca91b2abf9bdf9dd8a0/rag/nlp/query.py)给标题、关键词、问题、正文等字段不同权重，进行分词、同义词和词语权重处理；[search.Dealer](https://github.com/infiniflow/ragflow/blob/8dc5b4dc56c18497a16d8ca91b2abf9bdf9dd8a0/rag/nlp/search.py)组织文本/向量候选、过滤，再按配置使用词语/向量融合或模型重排，最后选择返回内容。其关键词分数不是本项目BM25的同一分数，权重不能照搬。

**Dify：候选集合与最终评分分阶段处理。** [RetrievalService](https://github.com/langgenius/dify/blob/88529a0dcdda7ec680384915782bf14fa217da9b/api/core/rag/datasource/retrieval_service.py)支持多检索路径，hybrid分支汇总去重，按配置走加权或模型后处理。代码明确避免在hybrid的向量初召回阶段套用最终融合/重排阈值，因为分数不可直接比较，过早筛除会丢候选。还区分父子段/摘要命中与原段返回。并非所有路径或配置都有重排。

**Haystack：召回组件与融合组件可独立组合。** [DocumentJoiner](https://github.com/deepset-ai/haystack/blob/e4d2e4d95d80cf18a8b18d8e5b8d63296aad119f/haystack/components/joiners/document_joiner.py)提供拼接去重、加权合并、RRF及分布融合。它不证明某种融合对所有业务更优，也不等同语义重排模型。

共同值得借鉴的职责：Query处理、候选召回、去重/融合或重排、最终上下文组装分别有配置和观测。其实现并不意味着我们的6条规则应照搬百条候选或多个额外模型。

## 3. 我们的文档是否有问题

基于[本次真实结果](../reports/customer-agent-live-v1/README.md)、[当前B店政策](../fixtures/demo-foundation/policies/policy-foundation-m1002-2026.10.yaml)和生产chunking/child_index/retrieval源码：

| 审查项 | 目前证据 | 判断 |
| --- | --- | --- |
| 是否缺少答案 | R-LOST-001已有“LOST且无有效签收、经人工核验、整行实付金额” | 本例不是缺文档 |
| 是否解析切掉条件 | 当前规则整体返回，已保存同版本原文 | 本例未见切分损失；不能类推所有外部长文 |
| 是否适合客户表达 | 标题“承运商判定丢失”，正文含英文LOST；查询用中文且加了补发。多条规则共享退款/人工/在途用语 | 表达、术语和区分度值得测试，不能仅凭观察判定因果 |
| 索引是否充分利用结构 | 短规则embedded_text取正文；子段也来自正文，标题保留作展示 | 现表示未充分利用场景标题等信息 |
| 数据是否有代表性 | 每店6条合成短规则，覆盖范围有限 | 适合工程探针，不能证明复杂客服RAG的泛化质量 |
| 召回失败是否唯一原因 | LOST政策dense和BM25均第4，Top3遗漏；生成还混淆ORDER/SHIPMENT状态 | Query、排序与回答适用性须分别评价 |

因此“文档质量”至少分内容覆盖、条件完整、检索表达及评测代表性。应避免把所有失败都叫文档差，或认为补充数量就会改善。

## 4. 对本项目的具体建议

1. **先审查询保真性**：固定原输入/事实/历史，消解指代、保留否定/不确定/意图变化，不新增补发等诉求。先利用现有Agent动作，额外模型调用与扩展查询作为后续候选。
2. **检索表示与引用原文分开**：探索由现有标题、明确术语对应和条件构成的检索表示；原政策、条件/例外、版本与引用血缘保持。术语如“承运商丢失（LOST）”须区分物流UNKNOWN与退款操作UNKNOWN，不能随意同义替换。派生表示不自动成为新生效政策。
3. **候选召回与最终返回分开测**：当前线上dense维持基线；比较扩大候选、独立字段匹配、dense/BM25及有限融合/重排。原始条款只有6条时先保留完整同店规则基线，评估多阶段检索是否有实际收益，不为架构复杂度加模型。
4. **分层归因**：原Query/保真候选Query × 原检索/候选检索四组；用完整规则诊断回答层问题。标注必要条件/例外是否找齐，区分命中任意相关条款与完整依据覆盖。旧已查看数据不称盲测。
5. **知识规模分开验证**：沿用先前约定，外部原始政策文档用于较大规模检索评测，商城政策用于业务端到端补充。已有外部文档/标签与历史报告不重写，外部政策不自动变成本店规则。
6. **效率单独测量**：模型加载、query embedding、数据库读取、排序与重排、完整工具耗时分开记录，分别测冷/热路径。当前每run新建embedding对象，其模型缓存仅对象内，应验证进程级复用和预热。多查询/重排需一起计时和计费，不预设更快。

已做过的[标题正文实验](../reports/rag-batch4/README.md)在当时dev上退化，不能把简单拼接当确定修复；字段加权/术语等新候选仍需新对照。本次没有实施上述候选，没有调用模型、重建索引、更换框架/依赖或启动业务服务。
