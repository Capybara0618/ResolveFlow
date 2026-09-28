# 审查员工作台交付记录

2026-09-28，用户主导优化方案的第一批实现。

## 可用行为

- 按工单角色/商户读取当前可操作项及绑定政策原文，不暴露内部服务接口。
- 无授权时可拒绝或要求补证，记录人、理由及问题编号；修订递增使旧调查结果失效。
- 人工方案显式选择材料和政策，校验材料归属/version/hash；金额由Java重算，仍需单独审批。
- 审核表单冻结打开时版本，409后刷新；核验后提示重新查看方案，已消费授权禁止再次输入。
- 待审、待补证、处理中、待确认、已结束、全部列表及查询；退款结果、人工决定记录可读。
- Schema、前端类型和 reviewer-context fixture 同步；保留原队列参数行为。

## 验证

- 新接口先跑4项失败测试，均因接口不存在返回404；实现后通过。
- `java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am spotless:apply -Dtest=ManualProposalApiTest,ReviewDecisionApiTest,ReviewedEvidenceApiTest,ReviewQueueApiTest,AuthorizationConsumptionApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：47 passed / 0 failed / 0 skipped。JDK21，测试使用独立Testcontainers MySQL。
- 首次扩展测试写入生成列 live_marker 失败，随后消费状态缺审批字段也被数据库约束拒绝；改为先按真实API审批，再模拟消费。跨商户样例最初误用未配置政策的商户，改为既有 M-2002 fixture。均保留原断言，没有绕过约束。
- `pnpm --dir web test`：7文件30 passed，含人工方案必选依据、冻结版本、409、只读及上下文过期。
- `pnpm --dir web build`：通过。
- OpenAPI YAML及内部引用检查、reviewer-context fixture JSON Schema验证通过。
- Windows追加CSS产生的换行空白已统一LF；差异检查通过。

## 边界

本批未调用收费模型，尚未验收新页面的浏览器效果或部署后完整退款。Agent结构化调查输出及真实模型质量后续继续；不将本批界面能力当作模型效果提升。既有共用资金边界测试保留；消费保护测试已随本批验证。历史日志、数据库与费用记录未提交。
