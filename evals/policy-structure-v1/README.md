# 原始政策结构草稿 v1

2026-10-06，绑定[四份原文来源](../policy-documents-v1/README.md)。本目录只保存正文定位、章节层级、表头与上下文关联的结构草稿，不保存第三方政策全文，不是商家政策、检索Gold或独立人工审核。

`manifest.json`绑定原来源manifest和`profiles.json`字节hash；后者每个标题/表头标记绑定具体block ID、文本hash、原片段hash。JD正文容器从div.content缩到div.contxt，去除面包屑、下载入口和正文外推荐链接；原来源清单/hash及旧解析报告不改。其他两来源保留原正文范围。仅按DOM布局定位，不按退款关键词删内容，宜家隐私/组装等非售后章节仍保留。

`annotation_origin=CODEX_STRUCTURE_DRAFT`明确这些是Codex阅读结构后的草稿；`PENDING_HUMAN_REVIEW`和独立复核0不能冒充专家审核。加粗文本不会自动变标题，普通td不会自动变表头；配置记录可审查的解释，并非按测试问法/最终动作写答案。

## 本机复现

在项目根目录运行，原始HTML缓存需保留；纯离线，不依赖Docker或API密钥：

```powershell
agent/.venv/Scripts/python.exe scripts/policy_drafts.py --output tmp/policy-documents-v1/drafts-next.json
agent/.venv/Scripts/python.exe scripts/policy_drafts.py --audit-encoder --output tmp/policy-documents-v1/drafts-audited-next.json
```

输出路径须不存在。第二条使用现有固定revision的本地BGE/SentenceTransformer tokenizer测长度，包括特殊token、不截断、无收费API。缺本地模型/依赖明确失败，不改用字符估算。警告提示长输入是预期诊断，当前只测长度、不将长输入送入embedding前向计算。

## 结果的含义

- 每个正文块只直接归属一个章节，保存原文定位与hash；章节另列完整子树，条件/列表/表格不被改写成摘要。
- `CONTEXT_REQUIRED`是候选关系：例如检索总则时需核对附注和排除条件，检索类目条件时需核对注意事项；层级父节的直接内容也会带回。关联闭包有visited集合，双向关系不重复文本、不无限循环。
- 检索表示`retrieval_text`与候选完整依据`context_text`分开，实际顺序按原文排列。表头草稿保留original_header/header_origin；原解析告警不隐藏，合并表格逻辑仍未展开。
- 草稿始终publishable=false/indexable=false。当前完整章节不是最终chunk；29个候选中16个超过512 token，必须进一步拆为长度可控的检索子块，并保留到章节/附注/例外的引用关系。不能直接使用SentenceTransformer默认截断来建索引。
- 候选关系可能过宽或遗漏，独立复核仍为0；完整上下文可能很长，不代表可直接塞进Agent请求。不对范围外服务新增执行权限。

实际证据见[集中报告](../../reports/policy-document-ingestion/README.md)及[结构/长度统计](../../reports/policy-document-ingestion/draft-summary.json)。后续先做有实际token门禁的子块/依据分离实验，再新语料query标签和检索对照；未经标注不计算检索准确率，不覆盖原calibrated-v3。
