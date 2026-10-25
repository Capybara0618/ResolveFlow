# 条款定位与父块去重：开发实验

2026-10-25，用户授权针对组合证据遗漏开展独立实验。[事前协议](../../docs/customer-rag-clause-experiment-v1.md)固定六路/40开发题/三轮720请求。当前先完成准备，不把目标写成收益。

## 准备与边界

- 复用冻结v3全部原文/100题Gold/344父块/模型权重，新增子片段索引；短原文fragment独立定位，已有长表格表头与正文仍绑定，不靠题号或Gold选块。最终回传同一父块，Top3不同上下文、8000字符/4096token预算对各组一致。
- 六路：原packed-ce当批参照，clause-dense、clause-bm25、clause-rrf，以及clause-ce-naive（前三子命中直接映射）/clause-ce-grouped（先父块去重再取前三）。表示能力和去重分别对照，不将全部收益归因于精排。
- 先两个模块缺失收集失败，再10检查通过；覆盖全部原Gold跨度、父绑定来源/版本、重复父块占位、相同上下文对象、完整矩阵/重复/非有限计时拒绝。四个新Python文件Ruff导入排序修正后通过，既有Starlette/anyio弃用警告保留。
- 准备命令：`python -m scripts.customer_rag_clause_experiment_v1 prepare`，实际子块数量及模型窗口记录于[preparation.json](preparation.json)。真实本地CPU编码子向量，不生成新Query、不运行题集排名，不调用生成API。

新manifest冻结并精确提交推送后只执行一次720请求。60验收题、上线、Agent和PDF不在本批范围内；不在看到结果后增加网格或回填旧结果。实际进度仅tasks/todo.md顶部。
