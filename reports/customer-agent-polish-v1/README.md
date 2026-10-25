# 客服等待与呈现根因核查

2026-10-25，输入为原[页面真实请求](../customer-latency-browser-v1/runtime-results.json)，不重写旧结果。脚本`scripts/diagnose_customer_wait_v1.py`只加载持久决策/工具响应，在当前SDK重放，不连数据库/HTTP、不发模型请求；deadline仅在离线副本延长，原报告不改。

[修正前](before.json)：tokenizer首次加载305ms，已预热SDK/装配5次中位60ms，模型journal起点相隔2140.708/1244.753ms。这两个间隔不是精确供应商耗时，包含各自生成、校验与工具；不能由此证明TLS、RAG或首token各耗时多少。原Java日志首delta5429.744ms保持。计数器冷加载是可迁出的本地等待，串行模型链路是主要等待区间，仍需细分计时。

第一步：ground_answer可按(field,source_id)去重展示，但逐项原校验/引用/事实、原摘要均保持；engine只对orchestrated-v1打开。navigation在实际有refund_summary时采用准备卡片后的简短确认指引，保留异步准备和用户确认边界，不声称已提交或已创建卡片。无摘要和旧架构仍走原入口教程。

新增7测试先4失败/3通过，修正后与navigation/fact_fields/orchestrated_engine/orchestration共80通过。扩大全部unit的support匹配525通过/6既有跳过/1828未选，首次误指定不存在contracts目录而0测试，已纠正命令；不当全仓成功。[原决策修正后](after-presentation.json)仍3次脚本决策，最终506→448字符，重复物流字段2→1；退款摘要、记忆和dialogue逐字保持，模型两段解释未删除。离线耗时不作真实提速百分比。

Ruff五文件通过（首次pairwise规范已修正），生产三源码strict mypy通过。当前0新增供应商/业务写入，usage2378，项目保持关闭。后续按[本批设计](../../docs/customer-agent-polish-v1.md)接续冷启动预热和精确计时，不用降低输入校验/政策要求或重试刷分解决延迟。
