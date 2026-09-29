# 已消费授权的输入冻结修复

2026-09-29记录，代码与测试于2026-09-28完成。

退款明确失败后工单可回到待审，但授权仍已消费。原有材料、人工方案及取消接口仅检查工单状态，可能在此时重新修改输入；新工作台的保护不能替代旧接口的保护。

新增授权消费存在性查询；材料追加/核验、人工方案、取消均在持有工单锁时检查。工作台可操作项使用同一消费事实；历史已消费授权也不可被后续记录掩盖。不改数据库迁移、退款结果或金额。

验证：新增四个参数场景先失败。人工方案和取消实际返回200；材料负例起初误用source_type导致400，已改为协议字段evidence_kind；核验路径在冻结检查缺失时继续查无效材料并返回422。实现后四项均返回409，且工单version/revision、方案数量和CONSUMED状态保持不变。

实际命令（JDK21，独立Testcontainers库）：

- Maven case-service `ManualProposalApiTest,ReviewedEvidenceApiTest,AuthorizationConsumptionApiTest`：35 passed / 0 failed / 0 skipped。
- Maven case-service `EvidenceApiTest,CaseCancelApiTest`：16 passed / 0 failed / 0 skipped。
- 第一次附加命令误写两个旧测试类名，未将其计为通过；已用上面的实际类名补跑。
- `spotless:apply`通过，未调用收费模型。

补充：上一批提案Schema写入时出现Windows CRLF差异，已在独立提交bff5c79统一LF；协议55项测试通过，未重写已推送提交。
