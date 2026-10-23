# 固定操作指引：真实回归与失败

2026-10-23，工程24d840f、准备13b163e。[方案](../../docs/customer-agent-navigation-v1.md)及[冻结清单](../../evals/customer-agent-navigation-v1/manifest.json)固定一次三会话六轮，沿用前批已见问题，使用新会话/run。**真实结果3轮发布、3轮失败；不能宣布收口成功。** 旧六轮失败/原文/清单未改，本批不继续付费重跑。

已实现模型选择MERCHANT_REVIEW/REFUND_APPLICATION并引用本run指南，程序生成固定入口、预览确认/未提交说明，然后进入原事实、事项、来源、金额检查。无新增业务执行权限，两阶段和唯一AgentScope循环保持；navigation.py及模板纳入manifest。

| 轮次 | 实际结果 | 关键证据 |
| --- | --- | --- |
| C01-1 | 失败 | 已读物流，选择人工核查却把O1物流当指南；修复仅猜O2，没有实际读取指南 |
| C01-2 | 失败 | 暂停原事项、读取指南、选择退款均正确；普通否定说明中“请商家核查”仍触发按钮名禁用 |
| C01-3 | 失败 | 原事项恢复、家人陈述REPLACE、物流/指南读取均正确；一般核查说明再次被按钮名校验过度拦截 |
| C01-4 | 发布/完整 | 一次修复后人工核查入口正确；再次替代家人陈述，保留原未收到与门卫排查 |
| C02-1 | 发布/完整 | 实际物流及本店政策，保留丢失核验条件；两个操作由程序分别生成入口，没有混用 |
| C03-1 | 发布/完整 | 独立人工咨询、预览编辑、选择共享及私聊边界完整 |

源审是Codex逐项核对，非独立人工Gold或统计效果。[完整对话/未发布决定](conversations.md)、[逐轮源审](review.json)、[统计](statistics.json)、[完整原始请求/响应/持久调用账](runtime-results.json)可核查。raw SHA256为`7e873e6d11c19b2165d4795543d1630f80ed1467e34dae6c77c78925d16fbf86`，失败不补算成功。

根因分两项：程序把按钮同名的普通中文表达也视为路由，校验过严；缺指南反馈同时要求“先读取”和“重发完整答案”，模型没有执行补读而直接猜引用。六轮均产生一次修复，增加调用并降低可用性。模板方向在已发布答复中有效，但不能把拦截错误文案当成整体体验成功。随后[离线修正](../../docs/customer-agent-navigation-fix-v1.md)只收窄校验到固定页面名，允许普通核查说明；缺来源反馈给出明确的先读取动作。[诊断](diagnostic-final.json)中本批保存决定5通过/1未读指南仍拒绝，旧两条错页仍拒绝；不是新增真实结果，不回填3/6，不追加收费重跑。任意同义错误路由仍不是通用语义检查器。

共28次真实deepseek-flash请求、10工具调用，6run/38调用账导出；Provider输入66538/输出3547、estimated=false，Harness保守输入78357另列，usage1949→1977。六轮合计40.416秒，预热8.351秒另列；一次本地政策检索约91.07ms，仅单次观测，不是SLA。C02额外退款步骤及成功答复重复解释偏冗长，尚可精简。失败后接纳的记忆/事项仍继承，两次REPLACE生效，但跨消息同义门卫条目仍有重复。

工程回归264通过（8.61秒），含两阶段/会话更新实际隔离PG及0调用恢复；4源码strict mypy/相关Ruff通过。新准备4通过（3.28秒），清单/权重/数据库执行前后预检通过。误从agent目录检查根脚本产生E402，按既有目录分别检查通过，未改规则。Java/网页、并发压测和旧冻结readiness未重验。

本批模型/本地BGE/保留政策检索真实，接口经ASGI及隔离PG；Commerce/Case事实为原固定合成HTTP，不冒充真实业务整链。[保全hash](preservation.json)中public11表全行hash及原四脏文件/旧raw/旧清单共8文件hash与执行前相同，隔离schema已导出并清理，未改物流、资金、分享数据、旧指标或简历。原业务服务维持停止；PG收尾已停exited/0、原卷保留，十个项目端口无监听，usage锁释放。

后续离线修正的集中回归270通过（9.84秒），新增保存决定测试后相关定向30通过（3.04秒），3源码strict mypy与相关Ruff通过；提示行过长已拆行，不改规则。诊断重复输出一致，旧真实清单因guidance.py变化明确拒绝恢复，原清单/结果保持。新增真实请求0，不据此把实际3/6改为5/6。

主要实际命令（execute已执行，不重复运行）：

```powershell
# agent目录，已配置实际隔离PG测试环境
.venv/Scripts/python.exe -m pytest $suite tests/integration/test_support_staged_api.py tests/integration/test_support_conversation_update.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_navigation_v1.py tests/integration/test_customer_agent_navigation_v1.py -q
# 仓库根目录
agent/.venv/Scripts/python.exe scripts/customer_agent_navigation_v1.py --check --database
# 以下诊断可离线运行；上面的旧清单在后续修正后应报告frozen source changed
agent/.venv/Scripts/python.exe scripts/customer_agent_navigation_diagnose_v1.py --output reports/customer-agent-navigation-v1/diagnostic-final.json
```
