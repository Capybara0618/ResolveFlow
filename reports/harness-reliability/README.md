# Harness 可靠性修复结果（2026-10-05）

## 第一步：具体字段纠错

按[规格](../../docs/harness-reliability.md)实现未发货退款拒绝的字段反馈：列出当前绑定来源的占用、付款、履约版本及整数分余额条件；不会把失败条件直接转换成拒绝，也不将客户文本插入纠错指令。一次修正及资金门禁保留。verifier v6；后续源码变更需新独立回放。

先失败测试7项均失败（fields-before.txt）；修复后82项通过（fields.xml/txt），覆盖具体字段、占用后人工交接、已有退款来源/引用和有限文字事实检查，Ruff通过。最初测试误接不存在的 runner.gate，已修正为直接验证真实 ActionGate；其后保留正式7项失败结果。

实际命令：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_harness_reliability.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_harness_reliability.py agent/tests/unit/test_investigation_sources.py agent/tests/unit/test_proposal_verifier.py agent/tests/unit/test_correction_loop.py agent/tests/unit/test_harness_manifest.py -q --tb=short --junitxml=reports/harness-reliability/fields.xml
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml agent/src/resolveflow/harness/verifier.py agent/src/resolveflow/harness/correction.py agent/src/resolveflow/harness/manifest.py agent/tests/unit/test_harness_reliability.py
```

交替重复调用和429恢复尚在实施；未跑本批集中PG/MCP/strict、真实模型复测、Java整链或网页。没有收费调用或常驻服务重启，不宣称建议质量提升。已有全项目mypy16个错误基线保留，待集中检查。
