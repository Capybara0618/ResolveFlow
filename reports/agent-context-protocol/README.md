# 常驻规则与短引用批次结果

2026-10-05，按用户批准保留五个 MCP 工具直接可用，精简常驻规则、工具用途说明及证据引用。规格见[本批说明](../../docs/agent-context-protocol.md)。本批没有工具发现平台、额外 LLM 摘要、RAG 算法调整、收费调用、worker 部署或日常工单重算。

## 已实现

- 五工具名称/只读权限/参数校验不变，增加简短用途说明；已有两个本地能力不变。动作与建议协议仍常驻，没有新增模型发现轮次。
- 常驻系统规则从 438 字符/942 UTF-8 字节到 204 字符/540 字节，相关材料/订单/物流/政策解释按已提供或已读来源注入。工具及动作协议1430→1418字节；没有宣称只靠改格式就大幅削减协议体积。
- 模型用 O/P 编号引用，来源头保留工具、来源类型/authority、版本，事实/冲突/note、政策全文/条件/例外保真。完整路径/哈希存在后台原始记录及当前包映射，提交前展开并继续原严格引用、权限、主体和 Java 契约检查。
- SDK 和回调使用展开的规范动作；落库模型响应保持原始编号。原始记录确定性重建映射，三个中断窗口及短编号原文读取恢复通过，不增加网络/模型调用或重置预算。
- context v7 冻结六条当前 strict 包于 `evals/replay/context-v4`，包括编号读取/建议；旧包、输入/Gold不覆盖。读取参数按前序记录展开并校验 hash，strict 仍不访问网络/业务写入口。

## 集中验证

| 检查 | 实际结果/证据 |
| --- | --- |
| Python 31 个相关模块 | 350 passed，0 failed/skipped；[JUnit](tests-final.xml) |
| 评测 CLI 完整性补充 | 新增缺0/缺1轨迹两项拒绝测试，所在模块29 passed；与集中模块去重后352项，不把重跑计为新覆盖 |
| 固定32案例/真实SDK、隔离PG、MCP、本地embedding | 32/32脚本联合/动作，148调用，0禁止动作/异常/未完成；[原始报告](mock-complete.json) |
| 独立Harness | 28/28；[报告](harness-final.json) |
| 当前strict回放 | 6/6；[报告](replay-final.json)；记录缺失/篡改等失败边界由集中模块验证 |
| 冻结v1/v2数据校验 | 均通过；[计数](frozen-data-validation.json)，商家3/bundle6/案例32/查询60不改 |
| Ruff/差异/文档链接 | 本批源代码、测试、CLI和测量脚本通过；精确暂存差异检查通过 |
| 全项目mypy | 69源码，9个既有文件16错误，未新增诊断；[输出](mypy-final.txt)。全项目类型门禁仍失败 |
| 业务库/收费调用 | public仍4COMPLETED/15模型/10工具/8回调，无测试schema遗留；[记录](database-final.json)，新付费调用0 |

32案例使用冻结脚本的完整对象输出兼容路径；新编号输出由独立SDK/恢复/回放测试覆盖。它们不代表真实LLM准确率或真实成本改善。

## 同轨迹体积对照

对照上一批 `reports/agent-context-batch2/mock-complete.json`，输入/Gold未变，32例行动和148调用数一致。

| 保守UTF-8字节估计 | 上一批 | 本批 | 变化 |
| --- | ---: | ---: | ---: |
| 32例首轮合计 | 124639 | 116031 | -6.91% |
| 148请求累计 | 867646 | 778567 | -10.27% |

当前最大单步7126，所有请求都在对应cap内。测量保存实际消息而非近似草稿；[可复算脚本](measure.py)/[逐例与报告hash](measurements.json)。UTF-8字节估计不是供应商token或账单，不能宣称费用下降10.27%；长材料元数据/政策仍可能真实超限，原超限转人工语义保留。

## 命令与初轮问题

根目录执行，隔离PG配置：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_short_references.py agent/tests/integration/test_short_reference_recovery.py agent/tests/integration/test_context_wiring.py -q
agent/.venv/Scripts/python.exe scripts/agent_eval.py mock --split all --output reports/agent-context-protocol/mock-complete.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py harness --output reports/agent-context-protocol/harness-final.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --output reports/agent-context-protocol/replay-final.json
agent/.venv/Scripts/python.exe reports/agent-context-protocol/measure.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_evaluation_controls.py -q
```

集中31模块命令的完整清单记录在[验证命令](verification-commands.json)，JUnit覆盖相应350项。Ruff使用 `--config agent/pyproject.toml`；mypy从agent目录执行 `.venv/Scripts/python.exe -m mypy`，退出1。新六包通过 `RESOLVEFLOW_REPLAY_GOLDEN_DIR` 与 `RESOLVEFLOW_SHORT_REF_GOLDEN_DIR` 指定当前目录，运行原五条记录测试和新短编号轨迹测试生成，6 passed/9 deselected；只生成指定轨迹，不运行已提交包检查，随后集中检查全部包。

初轮失败如实保留：新模块未实现时测试收集失败；测试误用不存在的事实字段名/错误fixture哈希，修正为现有契约事实键和原fixture值；导出对严格枚举使用dict解析失败，改用现有JSON解析约定；新增六包后CLI仍硬编码五包而失败，按profile声明增加六包门禁，并补缺轨迹失败测试。未删除引用/权限断言，没有调整Gold使其通过。

未运行：付费Live语义对照、专家人审、新RAG召回实验、Java业务整链、网页验收和worker部署。本批无Java/网页/资金协议改动，日常run不静默换manifest。已有四个工程/verify/Commerce测试改动及历史图/日志不夹带。本批精确commit、普通push及远端确认在收口回复提供。
