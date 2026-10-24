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

## 第二步：生产提示、纠错、持久化与流式

`stages.py`生产两阶段实际提示与样例切换fields-v1，`guidance.py`按明确协议给修复反馈，旧反馈仍保留。`service.py`新manifest显式记录answer_fact_rendering，已有代码/提示hash也随版本更新。不改变SDK轮数或增加修正额度。新增单测3项证明新协议修复反馈、退款摘要/指南和实际提示；流式集成保留旧用例并增加新协议及旧在途manifest拒绝。

命令与结果：

- 第一组6文件unit（新facts、grounding、staged、refund_summary、guidance、response_contract）最终 **80通过**。中途把旧single兼容提示也扩写，导致3条指南测试CONTEXT_REQUIRED_OVERFLOW；已完全撤回engine.py改动，保持single原提示/预算，之后80全过。没有通过增预算或删断言解决。
- `rg --files agent/tests/unit`选取support/相关contracts/customer_agent_publication完整组：**385通过，1已有历史诊断失败**（386总项，23.14秒）。`test_customer_agent_publication_v2.py::test_saved_acceptance_paths_pass_without_disabling_the_new_predicate`读取冻结v2指南，当前v3导航检查拒绝；使用`git show 42d5544:.../stages.py`恢复旧提示做只读同样诊断，错误仍为next_steps.source版本不匹配。navigation/旧raw/旧断言未改，不把此组报全绿。
- 显式临时PG端口55433：`pytest agent/tests/integration/test_support_stream_runtime.py agent/tests/integration/test_support_store.py agent/tests/integration/test_support_staged_api.py agent/tests/integration/test_support_answer_parts_api.py -q --tb=short`，**16通过，0跳过，8.26秒**。新格式解释逐段SSE、最终程序事实、失败候选撤回、实际PG存储与已完成run零新HTTP复用通过；未完成旧manifest不匹配且0模型调用。模拟Provider只证明接线，不计真实模型效果。
- `mypy --strict` stages/guidance/service **3源码通过**；Ruff本批源码/测试/脚本通过；diff检查通过。
- `PYTHONPATH=agent/src python scripts/review_customer_fact_fields_v1.py`：只读原保存候选精准重现占位符错误，另以添加版本、替换原宏为指向事实段的解释创建实验副本；两part可渲染。见[诊断原文/明确变换](offline-review.json)。0Provider、0业务写，不更改原raw或记为真实模型成功。

原服务/status健康，尚未加载本批Python；无新模型，usage2093。下一步保留数据加载当前代码、仅一次新合成问句验证正式发布/实际SSE及自动摘要可编辑；不重复商家调查/退款执行验收，不重发旧失败题。

第二步暂存差异检查发现新生成的offline-review.json使用Windows CRLF而被识别为行尾空白，PowerShell原命令未据原生命令退出码中断，提交74fe23a已正常同步。追加独立格式修复：诊断生成器改UTF-8字节写入，仅将本批衍生诊断文件CRLF改LF，JSON内容逐值保持，原始live-v2文件及其SHA不变。后续提交前显式检查退出码；没有改写历史commit或原始失败。
