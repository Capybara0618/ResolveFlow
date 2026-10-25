# 扩展售后政策RAG评测准备

2026-10-25，用户授权准备新数据集与四组入口，暂未运行新题排名、GPU精排或生成答案。Agent冻结稿与生产入口保持。

## 来源小步

- [方案](../../docs/customer-rag-quantification-v3.md)、[来源清单](../../evals/customer-rag-quantification-v3/sources.json)、[带原文定位的正文](../../evals/customer-rag-quantification-v3/corpus.json)已生成。15份HTML/7品牌域/939正文块/74247字符：原4份冻结快照+新增11份官方页面，URL/原字节hash/抓取日期可追溯。原始HTML仍在忽略tmp，不提交网站脚本、cookie或原始日志。
- 优衣库FAQ请求HTTP200但仅返回React页面外壳，无政策正文，已明确排除；改用可直接保存的索尼三包页面，不拿搜索摘要伪造完整正文。候选地址及失败快照保存在本机tmp，仅报告排除原因。
- 新提取器对明确正文根解析，保留原快照字符偏移、原文片段hash、表格及章节，不修改旧解析器。Apple页面有无关祖先noscript干扰旧遍历，通过独立定位唯一正文根后解析原始片段，逐块重新校验原HTML位置；不靠改写原HTML绕过hash。
- 先缺模块收集失败，接通后3单元通过；两项Ruff导入排序失败经自动整理修正。实际命令：`python -m pytest agent/tests/unit/test_customer_rag_dataset_v3.py -q --basetemp .pytest-tmp/rag-v3-data-green`、`python -m ruff check scripts/customer_rag_dataset_v3.py agent/tests/unit/test_customer_rag_dataset_v3.py`、`python -m scripts.customer_rag_dataset_v3 build`及`check`。check重建正文与原始HTML逐项一致。
- 文档有效日期缺失不补造，抓取时间不是政策生效时间；公开参考不发布为项目商家规则。品牌过滤后每题候选不同，后续报告实际规模。

来源小步只证明提取；未测新质量/时延。0生成API、未改Agent/线上RAG/业务数据库或启停服务。

## 问题与标签小步

[问题索引](../../evals/customer-rag-quantification-v3/README.md)/[100题与Gold](../../evals/customer-rag-quantification-v3/queries.json)/[数据审计](dataset-audit.json)已完成：五类各20，40开发（32可答）/60验收（48可答），103条原文跨度，15文档均有可答题。开发证据来自京东/有品3篇，其余12篇用于验收题，两组来源不重叠；作者见过原文，且部分文档沿旧数据，不称全新独立盲测。

每题包含品牌全范围scope、答案要点、必要原文及hash；20无法回答中8政策缺口/12实时业务或私有事实缺失，不从排名分数直接算拒答正确率。所有答案要点须在后续真实回答中逐项源审，关键词匹配不代替语义评分。

先模块缺失失败，再6检查通过（真实100题矩阵、造假quote、只选正确单篇scope、跨组变化、无缺失原因、重复ID拒绝），Ruff导入排序1项修正。`python -m scripts.customer_rag_questions_v3`实际核验全部103跨度逐字/hash一致、40/60及每类分层、原文来源不跨组。首次编写发现表格单元分隔符是` | `而非换行，按原表格第一行及表头修正引用后才写最终问题文件；没有运行排名后换题。

四路运行适配、向量构建/token窗口审计、manifest仍待下一小步；新题排名/答案/速度尚未测，0生成API/GPU新题推理，Agent与生产保持。
