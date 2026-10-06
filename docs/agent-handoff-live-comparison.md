# 建议交接改进：真实模型对照协议

2026-10-06，用户批准继续[上一批](../reports/decision-handoff/README.md)后的整体Agent对照。固定生产代码7e07700（context v13/verifier v7），不修改检索、提示或Gold后重跑刷分。

- 从calibrated-v3预选12例：A01B/A02B/A04B/A07B/A08B/A12B/A16B覆盖上次七项可读性警告，A15B覆盖引用未修复；A01A/A05A/A14B/A16A为未发货、物流、客户补证及质量正向对照。选择在运行前冻结，非随机样本、非盲测。
- 与reports/rag-delivery/agent-live.json同ID投影比较，原32例及Gold保持。模型deepseek-flash（用户所用Flash接口别名），temperature=0、thinking disabled、JSON、输出1024，单例model_calls=12及其余RunBudget保持；默认dense/BGE及完整政策保持。模型实际别名漂移、单次随机性与多项Harness变化不允许归因为单一算法效果。
- 每例一次；不自动再次收费、改错例输入或人工注入模型错误。用量连续记入已有账本，保留所有失败/未知usage。真实PG隔离eval schema、合成只读HTTP及真实MCP/AgentScope，非Java业务端到端，不启动常驻消费或退款。
- 自动检查复用原评分器；Codex逐例核对原始事实、政策、实际请求/响应、引用与下一轮反馈。标记CODEX_REVIEW/NONBLIND，按事实支持、政策适用、动作理由、责任与商家可读性分开评价。旧标签不改；未完成计入总分母，语义维度标NOT_COMPLETED。
- 引用错误若本次未自然发生，不能宣称真实模型纠错成功；已通过的mock恢复测试另列。ASK_CUSTOMER才产生客户问题，REQUEST_INFO仍是供商家处理的建议，ESCALATE全文仍未接网页。
- 评测结果/输入SHA/源码与逐例语义依据另存新版本。比较脚本只校验、重判已有自动分与聚合，不调用模型；固定前后完整ID，预算/provider/评分器不一致必须报错，不允许删失败或把旧32例与新12例总分直接相比。

一次集中验证后精确提交并正常推送。后续是否改自然语言提示、补网页转交摘要由结果决定；本轮不新增生产模块。
