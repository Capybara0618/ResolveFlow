# 当前客服链路计量与真实进程故障：集中接线验证

2026-10-26，接线实现c3aaf9c普通推送核实后，按[接线说明](../../../docs/customer-harness-context-wiring-v1.md)执行一次固定矩阵。**模型是MOCK_SSE，数据库和进程退出是真实的；没有新的模型质量、token节省或恢复降本指标。** 已冻结Agent/RAG简历文案及旧实验保持。

## 完成的验证

| 项目 | 实际结果 |
| --- | --- |
| 上下文检查点 | 16段×2检查点×2组，64脚本回答轮全部接线完成 |
| 实际SSE客户端发送到本地桩 | 上下文128次；故障前缀40次、续跑60次，共228次；不是真实provider/收费请求 |
| 请求与持久化 | 128份上下文模型body逐条等于PG保存请求，全部在8192输入预算内；1024输出上限保持 |
| 原文预算控制 | raw第二检查点5/16触发按时间裁剪，最多移除50条消息；仅说明预算确实生效，不是质量或压缩收益 |
| 故障矩阵 | 五任务×三窗口×两组，30次os._exit(73)，30次新进程接续 |
| 已保存窗口的恢复组 | 10/10脚本执行完成，已有模型/业务工具结果复用 |
| 模型响应未保存的恢复组 | 5/5明确UNKNOWN_MODEL_RESULT，0新发送；属于停止合同，不能算成功恢复或省调用收益 |
| 从头执行对照组 | 15/15脚本执行完成，新run继承原spend及绝对deadline |
| 隔离与旧执行者 | 30条deadline保持、spend单调、旧执行者STALE_FENCE；恢复组fence递增，manifest逐条相同 |

故障桩统一读取ORDER/SHIPMENT/POLICY以确保目标窗口可达，**这不是给正式模型规定调查路径**。工具故障逐题按business_fault_source命中实际业务来源，排除启动GUIDE。全部原始状态、真实退出码、STARTED/COMPLETE与前后快照都保留；未知窗口没有清除journal或重置预算。

## 证据与复算

- [固定执行manifest](manifest.json)：134文件hash，原始16段及54文件准备、当前客服代码/SDK适配、迁移、资产/锁、新驱动与检查入口。
- [上下文原始结果](context-mock.json)：64轮、128份实际SSE body/usage形状、各自实际状态和历史。semantic_quality为null，usage为脚本构造的100输入/30输出，不能引用为真实成本。
- [进程矩阵原始结果](crash-mock.json)：30条，包含每组前缀/接续原始模型记录、退出码、故障证据与完整run/call前后快照；semantic_quality及live_recovery_metrics为null。
- [数据库导出](database.json)：109个run、422条call，包含旧故障run和redo新run；在清理本次schema前导出。
- [最终审计](audit.json)：public数据前后哈希相同、schema集合恢复、134输入文件与9项保留文件哈希保持、自建schema已删除。旧4脏文件、累计收费账本3289及Agent/RAG/旧恢复结果均保持。
- [计量与PG集成测试](tests.xml)：7单元+5集成，共12通过/0失败/0跳过。另4次真实退出属于这些集成测试，不当作矩阵新增场景。已有Starlette/anyio弃用警告保留。

为避免重复提交，同一个job的spec/record/marker/audit及子进程日志仍完整保留在本机 `wiring-v1/crash-mock/`，不重复加入Git；各job原始模型/前后快照已完整包含在crash-mock.json，独立数据库副本在database.json。JSON检查无DSN、授权头或测试密钥，原始进程日志不提交。

实际命令：PYTHONPATH设为仓库/agent/src/agent，PYTHONIOENCODING=utf-8，HCTX_TEST_DSN仅进程内传入既有独立65433测试PG。

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_harness_wiring_check_v1 --output reports/customer-harness-context-v1/wiring-v1
agent/.venv/Scripts/python.exe -m scripts.evaluation.customer_harness_context_v1 check
agent/.venv/Scripts/python.exe -m ruff check scripts/customer_harness_wiring_check_v1.py
```

唯一新建schema为自动生成的t_hctx_ UUID前缀，执行后原始记录已导出并清理该schema，没有清库/删卷。只临时启动原有resolveflow-polish-pg-20261025（65433），结束后恢复停止；业务55433及原业务卷未操作，无残留故障子进程。Java/网页/GPU未启动或修改。

## 失败与剩余工作

实现阶段先因计量模块缺失收集失败，补实现后7项通过；Ruff导入/未使用项、宽泛异常断言与subprocess check参数修正后四文件通过。5项PG集成随后通过。集中矩阵入口先Ruff修正一项导入顺序，再冻结执行，矩阵无失败或重跑。原准备54文件hash仍通过，不重写旧报告。

当前只能说**新客服计量、状态接线及持久化故障合同已验证**。正式真实模型入口还需接共享收费账本/单写锁、明确请求上限和起点、正式执行manifest及逐轮保留/源审，不能直接把当前offline CLI换个URL就称正式评测就绪。后续不因得到脚本228次而将真实模型上限定为228；正式调用轮数由实际理解/调查/读回/纠错决定。无新简历数字，不自动收费、追分或修改生产恢复行为。
