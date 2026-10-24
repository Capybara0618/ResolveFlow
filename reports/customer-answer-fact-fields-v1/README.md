# 客服事实渲染修复

2026-10-24。[规格](../../docs/customer-answer-fact-fields-v1.md)。当前进度仅 tasks/todo.md 顶部。

## 第一步：版本协议与渲染

新增内部根级 `fact_rendering=fields-v1`，事实字段与解释正文解耦，由程序校验实际来源并追加中文标签事实段。无该字段仍用旧宏协议，旧缺宏失败保持。未改变公开 Java/Python 回调字段、依赖锁、工具路径、预算和资金规则。原完成结果继续原值复用，原在途 manifest 不静默迁移。

文件：`support/protocol.py`、`support/grounding.py`、新增 `test_support_fact_fields.py` 和上述规格。新19项覆盖 SDK 三种物流状态、单段金额、未知结论/多行选择、错误来源/字段/版本/金额、长度及旧协议。未知来源值保留原值，不把它猜成丢失。

实际命令（根目录）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_fact_fields.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_fact_fields.py agent/tests/unit/test_support_grounding.py agent/tests/unit/test_support_answer_parts.py agent/tests/unit/test_support_refund_summary.py agent/tests/unit/test_contracts_support_agent.py -q --tb=short
agent/.venv/Scripts/python.exe -m ruff check agent/src/resolveflow/support/protocol.py agent/src/resolveflow/support/grounding.py agent/tests/unit/test_support_fact_fields.py
agent/.venv/Scripts/python.exe -m mypy --strict agent/src/resolveflow/support/protocol.py agent/src/resolveflow/support/grounding.py
git diff --check
```

结果：首版红测14失败/1通过（新字段原协议拒绝）；实现后29项新旧grounding通过；补齐版本/多行断言后上述集中组52通过，Ruff/strict两源码/diff检查通过。只有既有 Starlette anyio 弃用警告。首次 PowerShell 花括号路径搜索语法失败，后改目录搜索；无业务影响。后续静态搜索一个旧 schemas 路径不存在，已转当前源码与合同，不作为验证通过。

本步无新增模型、业务库写入、服务重启或真实效果主张；原 usage 2093。实际提示/纠错/新run manifest和流式集成下一步完成。四历史脏文件不归本步，暂存只含已核实清单。
