# 新评测体系实施与验证

2026-10-04。实施进行中，进度只在tasks/todo.md顶部。范围见[规格](../docs/agent-evaluation-rebuild.md)。旧成绩不计入本报告，未改商城业务数据。

## 数据批次

新建三商家六政策bundle、60查询、32案例/16对，Gold独立，20个Harness与8个上下文检查清单。来源SYNTHETIC，标注policy_checked_by_codex_not_human。输入只读，manifest锁定hash；主场景隔离不是随机业务抽样。

先运行新增关键测试得到4失败/4通过（新文件尚不存在）；生成数据并修正工具订单主体与案例scope一致后，8项通过。覆盖嵌套答案泄漏、配对主体改变/事实不变、缺答案、不可区分答案和冻结hash。根目录Ruff全局配置初轮报告未使用noqa/字符串风格问题；按现有agent/pyproject.toml定点格式后Ruff通过。实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/build_assets.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_current_evaluation_dataset.py -q --tb=line
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/evaluation agent/tests/unit/test_current_evaluation_dataset.py
```

当前只完成数据协议与初版资产。尚未清理旧资产/跑RAG、SDK、Harness、Live或新回放；不将检查清单当成已执行结果。后续按五批统一执行和记录，不继承历史通过结论。收费请求0。
