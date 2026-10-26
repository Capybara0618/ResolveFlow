# 正式模型入口准备完成，尚未执行收费评测

2026-10-26。接续97cacb2的接线验证，按[正式运行边界](../../../docs/customer-harness-live-v1.md)完成共享账本、固定上限、正式manifest、逐轮持久化及可源审输出。**本批真实provider请求为0，无新上下文质量、token节省或恢复收益。**

## 已固定的正式计划

| 项目 | 固定范围 |
| --- | --- |
| 上下文 | 原16段×2检查点×两组=64回答轮，各一次，最多400模型请求 |
| 恢复 | 五任务×三窗口×两组=15组配对/30故障前缀，各一次，最多300模型请求 |
| 总上限 | 最多700新请求；当前账本3289，如原起点不变，最高累计3989 |
| 模型与循环 | 当前orchestrated-v1、生产AgentScope、DeepSeek Flash、temperature0、非thinking/JSON |
| 输入/输出/期限 | 8192输入、1024输出、provider容量32768；每run12调用，120秒原deadline |
| 评分 | 源审模板64检查点+30恢复结果；初始全null，不能把SUCCEEDED当业务正确 |

700是预算上限，不是目标或预计消费。所有失败和未运行保留；达到phase或总上限停止，不重开session或重跑失败补分。正式收费仍待用户确认本固定范围，未注入/读取真实模型密钥，未创建live-v1结果目录。

## 实现及验证

- [执行manifest](../../../evals/customer-harness-context-v1/live-manifest.json)绑定137文件；原54准备文件、旧134接线文件全部hash保持，新的运行脚本/预算模块/测试/规格加入新版本，不改历史manifest。
- [正式入口](../../../scripts/customer_harness_live_v1.py)提供freeze/check/execute/child；freeze/check不调用模型。父进程持有原全局账本锁，子进程使用owner环境令牌及短互斥预约同一session。session起点、plan、总上限和分phase上限不可修改；同输出重启仍继承已消费量。
- [预算模块](../../../scripts/evaluation/customer_harness_budget_v1.py)保留旧账本元数据，发送前持久化预约。失败/未知结果不退计数，可能“预约成功但未发出”的窗口保留不确定性，不宣称供应商精确请求数；与实际发送记录分别核对。
- 完成的上下文前缀可复用，第二检查点继承本组实际状态。STARTED/未知模型、未收录job目录明确拒绝自动重跑，需先核查原日志/PG；错误/预算停止导出并保留自有schema，完整运行才导出后清理。
- 发现旧脚本来源对所有任务均给DELIVERED，而恢复申请题写“未发货”。新增正式评测适配仅对该题给ORDER PAID/SHIPMENT NOT_SHIPPED，保持同一合成订单金额、权限与政策；覆盖后事实亦记入实际读取日志。原脚本接线材料/报告/生产代码不变，不拿原脚本成功冒充该题真实语义成功。

### 实际命令及失败

1. 新测试先因正式入口模块不存在收集失败；补预算/入口后9单元通过。
2. 既有独立测试PG65433临时启动，4集成+9单元13通过；再补完整execute导出/保留/前缀复用检查，14通过。测试账本在pytest临时目录，旧真实账本不写入。
3. Ruff导入/未使用项、固定子进程测试的静态告警及函数名行长修正后4文件通过。函数名修正后最终集中9新单元+5新PG集成+7原计量单元：[21通过/0失败/0跳过](tests.xml)。已有Starlette/anyio弃用警告保留。
4. freeze生成新的137文件manifest，check及旧prepare check通过；无正式execute。最终核对原54/134/新137文件、旧9保护文件哈希均保持；真实账本3289无lock，无新正式live输出/在途执行进程。独立测试PG恢复停止，原业务55433/卷/Java/UI保持。

实际命令（PYTHONPATH包含仓库/agent/src/agent，PYTHONIOENCODING=utf-8；测试DSN仅进程环境）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_customer_harness_live_v1.py agent/tests/integration/test_customer_harness_live_v1.py agent/tests/unit/test_customer_harness_measurement_v1.py -q
agent/.venv/Scripts/python.exe -m ruff check scripts/customer_harness_live_v1.py scripts/evaluation/customer_harness_budget_v1.py agent/tests/unit/test_customer_harness_live_v1.py agent/tests/integration/test_customer_harness_live_v1.py
agent/.venv/Scripts/python.exe -m scripts.customer_harness_live_v1 freeze
agent/.venv/Scripts/python.exe -m scripts.customer_harness_live_v1 check
agent/.venv/Scripts/python.exe -m scripts.evaluation.customer_harness_context_v1 check
```

## 下一步

按上述64轮/15配对/最多700新请求确认授权后，使用同一新输出路径一次运行；若账本起点变化先核查，不覆盖旧量。真实调用/业务事实仍为合成源，不能称商用客户盲测。完成后按原文和实际输出逐项源审，汇总上下文通过率及输入成本、恢复完成及新增请求，并保留UNKNOWN窗口失败。用户未确认前不收费、不改简历冻结稿、不为得到旧16.4%调整生产恢复规则。
