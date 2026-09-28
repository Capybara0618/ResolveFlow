# 评测数据集

当前核心规格是80个合成业务案例（40 dev / 40冻结 test），另有20个独立安全样例、40条RAG查询；见 `docs/evaluation.md`。旧T23的240案例方案不是现行验收量。

`h1-pairs-input.json` 是首批12个**合成** H1 配对案例输入，全部预分配到test；同组A/B的诉求和主体相同，权威事实不同。`h1-pairs-gold.json` 单独保存允许/禁止的终局动作、必须观察字段和引用要求。Gold目前标记为 `draft-not-human-reviewed`，提交后按版本冻结，人工审查与真实服务seed仍待完成。不能用这12例调Prompt后又作为未触碰的test统计。

离线校验：`python evals/datasets/h1_pairs.py`。导出单例：`python evals/datasets/h1_pairs.py --export-case H1-01-A`。导出的是**评测执行器的seed输入**（包括模拟权威事实），不得直接作为Agent的模型消息；执行器应在隔离数据域把事实写入Case/Commerce/政策工具，再仅以原诉求创建run。Gold绝不可进入run、工具返回或模型上下文。`h1-run-record.schema.json` 是后续live运行的最小记录结构，失败/超时/跳过也留样本。当前没有H1服务seed/runner、没有live结果、没有人工Gold审查，不据此勾H1。

2026-09-28：用户取消 C12，专属未提交样本已删除。保留历史 H1 资产供按需参考，不作为当前任务。
