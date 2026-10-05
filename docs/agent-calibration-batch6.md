# 第六批：输入校准、上下文计量与可修复反馈

2026-10-05 用户批准执行。接续第五批证据，不重建已完成体系或自动扩展检索算法。

1. 冻结 `evals/calibrated-v3`。UNKNOWN/PENDING 是旧样本混写的退款操作语义，合法订单行槽应为 RESERVED；未支付商城草稿不生成 order_line，作为越过 Java 入口的来源缺失边界探针返回 404。全量预检另发现 SIGNED 非合法承运枚举，改用 DELIVERED。16份原非法案例另存为负向契约样本，旧 v1/v2、Gold、报告、回放全部保留。
2. 只对 DeepSeek provider 的 deepseek-flash 使用官方 V4.1 tokenizer，固定上游 commit 与原文 hash，复用已有 tokenizers 依赖。计数取消息正文与完整 JSON 估计的较大值，加一次 256 包装预留；仍标记 ESTIMATED，实际 API usage 才是用量证据。其他模型保留 UTF-8 字节上界；资产损坏明确失败，不能同 run 静默降级。ContextPacket、持久预留、manifest 使用相同计量版本，旧 run 不换 manifest。
3. 同版本政策采用无损表格，仅省重复字段名和共同 bundle/version，全文、例外、来源编号均保留；不同版本不得合并。非法引用反馈说明可用来源种类及编号，格式错误提示扁平协议和人工接管合法格式；不自动补引用、不增加修正次数或绕过安全拒绝。
4. 集中验证契约、评分负例、上下文保护、SDK/恢复/fence、工具失败、独立 Harness 与新版本 strict 回放。真实复测固定第五批十个联合失败例及正向控制；记录完整分母、真实 token、每次调用与失败，不能将跨数据版本分数称为受控提升。

没有独立人审 Gold，不宣称真实泛化准确率；不修改 Java 审批/资金权限，不清日常数据或 usage ledger，不部署常驻服务。状态只维护 tasks/todo.md 顶部。

官方依据：[V4.1 tokenizer 使用说明](https://github.com/deepseek-ai/deepseek-recipe/blob/8cadfede7063c896b944e7bae05daa3549ae97ea/docs/tokenizer.md)、[API token 用量说明](https://api-docs.deepseek.com/quick_start/token_usage/)。本地 tokenizer 计数不等于在线模板及服务内部处理后的精确计费数。
