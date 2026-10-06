# 检索表示与来源块去重实验 v1

2026-10-06，复用policy-query-v1的29问/41依据原子、4文档/66子块及前批基线。标签仍是作者草稿，独立人审0；本批只做可解释实验，不改变商家政策、生产索引或旧标签。完整章节路径可能改变词权重，不能预设“加标题一定更好”。

`manifest.json`在新表示排名前冻结：旧query manifest、旧基线字节和相关依赖源码hash，固定body/title_path、dense/BM25、整context/原文块并集两种装配及总8000字符。query/标注/原文/切分/模型revision/依赖均不变；新表示在固定encoder512上限下先测token，不截断、不回退或缩短标题来匹配失败题。

## 两个独立变量

1. 检索表示：body复用原向量；title_path将已有章节路径作为前缀，正文完整保留，重新本地编码。来源/碎片区间仍指原body，不能把标题前缀算成命中原文证据。旧source块及Gold坐标不变。标题源于待审结构配置，有人工解释痕迹，不当成业务事实。
2. 上下文装配：在同一排名前2/5回查同一候选关联。baseline按完整context导出；block_union按source_id/raw_sha256/block_id身份去重，并按本文件原文顺序组合，不凭文本相同合并不同主体/快照。每个context要么完整所需块全部存在，要么整份拒绝；只有完全接纳的来源块计为交付。

并集会利用释放空间接纳后面的context，因此可能带回更多相关或无关内容。不是上下文摘要、相关性筛选、最优集合求解或必然覆盖不退化的算法。存在一个通用反例：新的早期context利用去重后空间被接纳，后续context反而被预算挡住；测试保留该取舍。若要求与基线严格相同信息集合，应先固定选中的context，再只做序列化去重，另冻实验配置验证。

## 本机运行

```powershell
agent/.venv/Scripts/python.exe scripts/policy_representation_eval.py --output tmp/policy-documents-v1/representation-next-report.json --cache-output tmp/policy-documents-v1/representation-next-cache.json
```

依赖前批本机原文/草稿/子块和现有BGE，不需要Docker/API密钥。两个输出路径均须是新文件；带正文和向量的cache强制留在忽略tmp，报告仅含元数据。body排名/分数（绝对容差1e-6）及计分须复现旧基线，否则整个实验失败；query、encoder/依赖版本或冻结源码漂移明确拒绝。不将生产改动混在实验中。

## 结果与决定

[完整报告](../../reports/policy-document-ingestion/representation-experiment.json)有116记录（29问×2表示×2路径），[源块审计](../../reports/policy-document-ingestion/representation-audit.json)核对232个排名前缀。body 58记录复现，title 66向量全部≤444 token/encoder512，未使用默认截断。

草稿17可答题中，标题路径使dense直接前5从9变7、父节前5从16变15；BM25直接前5仍12、父节仍17，但有个案互换。标题路径未通过这批诊断，保留失败，不部署；不为两条失败添加query/类目/政策ID特例，也不无限试参数追满分。

相同body排名，原文块并集将前5平均内容字数dense3446.79→2876.97（约16.53%减少），BM253425.72→2888.93（约15.67%减少）。所有116记录、232前缀本轮无基线来源块丢失、draft缺依据集合未变，被接纳context完整，总文本≤8000字。这只是固定样本上的结果，不证明所有场景覆盖单调性或LLM token安全。

body/dense有23问前5字数减少；body/BM25有21问减少、7相同、1增加。增加例由5913→7708字，因为去重释放空间后接纳了原被挡住的context；新增块未带来草稿必要依据覆盖增加，不能称噪音减少或上下文已最优。正式质量仍null，独立复核后才讨论召回/适用性和生产采用；下一步应分开“选哪些依据”和“如何无损表达”，同时验证LLM token/引用开销，而不是只继续扩大返回范围。
