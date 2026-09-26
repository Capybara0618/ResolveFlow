# C09生产恢复实施与验收（2026-09-26）

## 请求冻结小步

迁移008追加实际provider请求体、重建用历史spend、SDK状态及manifest字段；工具结果表供下一小步接入。`reserve` 将请求hash/输出ceiling校验与预占同事务提交，失败不扣预算；LiveModelClient提供发送前精确body接口，不包含鉴权header。测试先因错误导入未收集，修正后RED 2 failed（缺request_body参数），实现后请求/attempt/结果/live-client聚焦 **32 passed**。命令：agent目录 `./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_request.py tests/integration/test_recovery_model_attempt.py tests/integration/test_recovery_model_result.py tests/unit/test_live_model_client.py -q -p no:cacheprovider --tb=short`。尚未接SDK/worker，C09不勾；本小步不重跑全量/Java/live，C09最终验收重跑全量。
