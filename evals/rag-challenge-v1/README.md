# RAG 口语诊断集 v1

24条查询，三商家，沿用aligned-v2政策正文。query与Gold分文件，manifest固定文件hash及基础数据hash；先固定问法/答案再运行排序实验，不按排名改答案。

这是同作者按合成政策编写的口语、否定、信息不足和多依据诊断问题，**不是独立标注、真实用户语料或盲测**。每个政策版本仍只有9条候选，top5指标容易偏高。当前Gold等待用户/独立人员逐条核对；没有人审不能宣称真实准确率。

`queries.json`只有问题、主体、绑定版本和诊断分组；`gold.json`只有评分器使用的必要规则。检索表示、query embedding和排序均不读取Gold。Gold用于评分及检查标签是否引用现有条款，不用于选词/补候选。

生产query来自Agent的`SEARCH_POLICY`决策，不来自本文件。已有真实模型query另由诊断脚本从固定的三份live报告提取，保存源文件hash、案例/轮次和原top_k。它们是合成案例上的真实模型输出，未标注单次检索目标，不能套用终局案例Gold或并入准确率分母。

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/rag_experiments.py --output tmp/rag-new.json
```

需要现有PG和已锁本地中文embedding；只写隔离eval_* schema并清理，不改public或商家业务政策，不调用付费模型。输出文件存在时拒绝覆盖。候选“标题＋完整正文”仅离线实验，不自动部署；参见[规格](../../docs/rag-optimization-batch4.md)与[报告](../../reports/rag-batch4/README.md)。
