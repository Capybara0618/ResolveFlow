# 审查员核验、补证后的调查闭环

2026-09-29 完成，对应 `tasks/plan.md` 第一批。

## 已补齐的真实缺口

- 客户补证或人工核验使 `input_revision` 递增后，工单现在统一回到 `QUEUED`，并在同一事务写入该修订对应的确定性 `agent_binding`。旧方案仍可追溯，但不能继续审批。
- 新 run 的调度截止时间从该 binding 的创建时间计算，不再沿用工单最初创建时间；调度请求带上截至当前修订已经存在的证据 ID。
- 有授权与无授权两条 `REQUEST_INFO` 路径共用同一组约束：稳定 `question_id`、最多两轮、过期拒绝、等待客户期间不得重复追问。
- 客户回答已记录的问题时必须提交匹配的 `question_id`。错误或缺失 ID 返回 422，且不会推进修订；正确回答会保留问题关联并创建新修订 binding。
- 工作台明确显示方案所属修订、旧版已失效，以及当前正在排队、调查或等待补证的下一步。

未改变退款执行、金额规则、Agent 权限、同 run 的预算/deadline 或 manifest；未新增数据库迁移。

## 闭环证据

新增合成工单集成场景实际走通：第 1 版方案与授权形成后追加材料并完成核验，工单推进到第 3 版；旧授权审批返回 409；第 2 版迟到回调标记为 `STALE` 且不能覆盖工单；第 3 版回调被接受，当前方案和授权都归属第 3 版。数据库中保留两版方案用于审计。

实现前的定向失败暴露了两个缺口：修订递增后没有新 binding，以及授权路径的补证决定没有生成可关联的问题记录。对应回归测试在实现后通过。

## 集中验证

- Java 21，case-service 相关 8 个测试类：83 passed，0 failed，0 skipped。覆盖重新调查闭环、补证约束、迟到回调和消费后四个旧入口。
- 前端 Vitest：35 passed；`pnpm --dir web build` 通过。该结果在前端代码完成后取得，本次收尾未再改前端代码。
- `agent/tests/unit/test_contracts_openapi.py`：87 passed。
- Java `spotless:check`：通过。
- `git diff --check`：通过。
- 扩展运行 `test_contracts_core_routes.py + test_contracts_openapi.py` 得到 153 passed、5 failed。5 个失败均属于上一批已有的调查/来源路由 ownership/authority 登记与 review 队列参数断言，本批 `openapi-case.yaml` 差异未触及这些行；本批没有顺带修改该范围。

未运行全仓测试矩阵、真实收费模型评测和公网部署；未清理数据库或 Docker 卷。
