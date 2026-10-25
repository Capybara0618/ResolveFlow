# 扩展售后政策RAG评测准备

2026-10-25，用户授权准备新数据集与四组入口，暂未运行新题排名、GPU精排或生成答案。Agent冻结稿与生产入口保持。

## 来源小步

- [方案](../../docs/customer-rag-quantification-v3.md)、[来源清单](../../evals/customer-rag-quantification-v3/sources.json)、[带原文定位的正文](../../evals/customer-rag-quantification-v3/corpus.json)已生成。15份HTML/7品牌域/939正文块/74247字符：原4份冻结快照+新增11份官方页面，URL/原字节hash/抓取日期可追溯。原始HTML仍在忽略tmp，不提交网站脚本、cookie或原始日志。
- 优衣库FAQ请求HTTP200但仅返回React页面外壳，无政策正文，已明确排除；改用可直接保存的索尼三包页面，不拿搜索摘要伪造完整正文。候选地址及失败快照保存在本机tmp，仅报告排除原因。
- 新提取器对明确正文根解析，保留原快照字符偏移、原文片段hash、表格及章节，不修改旧解析器。Apple页面有无关祖先noscript干扰旧遍历，通过独立定位唯一正文根后解析原始片段，逐块重新校验原HTML位置；不靠改写原HTML绕过hash。
- 先缺模块收集失败，接通后3单元通过；两项Ruff导入排序失败经自动整理修正。实际命令：`python -m pytest agent/tests/unit/test_customer_rag_dataset_v3.py -q --basetemp .pytest-tmp/rag-v3-data-green`、`python -m ruff check scripts/customer_rag_dataset_v3.py agent/tests/unit/test_customer_rag_dataset_v3.py`、`python -m scripts.customer_rag_dataset_v3 build`及`check`。check重建正文与原始HTML逐项一致。
- 文档有效日期缺失不补造，抓取时间不是政策生效时间；公开参考不发布为项目商家规则。品牌过滤后每题候选不同，后续报告实际规模。

本步只证明来源提取；100题/证据标签、四路适配、token窗口审计与冻结仍继续准备，不能称新质量/时延已测。0生成API、未改Agent/线上RAG/业务数据库或启停服务。
