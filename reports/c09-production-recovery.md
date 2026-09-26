# C09生产恢复实施与验收（2026-09-26）

## 请求冻结小步

迁移008追加实际provider请求体、重建用历史spend、SDK状态及manifest字段；工具结果表供下一小步接入。`reserve` 将请求hash/输出ceiling校验与预占同事务提交，失败不扣预算；LiveModelClient提供发送前精确body接口，不包含鉴权header。测试先因错误导入未收集，修正后RED 2 failed（缺request_body参数），实现后请求/attempt/结果/live-client聚焦 **32 passed**。命令：agent目录 `./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_request.py tests/integration/test_recovery_model_attempt.py tests/integration/test_recovery_model_result.py tests/unit/test_live_model_client.py -q -p no:cacheprovider --tb=short`。尚未接SDK/worker，C09不勾；本小步不重跑全量/Java/live，C09最终验收重跑全量。

## 租约与session锁小步

RunLease保留独立pool checkout承载session advisory lock，领取与fence递增/STARTED同事务；网络期间只保留session锁，不持行事务。另一pool连接心跳续租，退出释放锁和心跳；同run锁仍被持有时即使lease过期也不夺取。恢复保持原active_deadline，STARTED不重复。RED缺模块→lease+worker **22 passed**（真实PG）；新增Ruff/strict mypy通过。生产worker接入/终局fence下一步完成，本步不勾C09，未跑全量/Java/live。
