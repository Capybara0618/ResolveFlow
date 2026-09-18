# 可靠性与安全 · v1.2核心

只覆盖保留的退款链路；不实现补发Saga、跨动作权益或执行中取消。详情见[领域状态](domain-model.md)。

## 1. 事务边界

- Case：授权消费CAS、固定operation、RefundRequested outbox同事务。
- Commerce：inbox去重、operation落库、金额/行占用同事务；provider调用在事务外。
- Commerce终局：operation、支付账、行退款状态、结果outbox同事务。
- Case：结果inbox、状态投影、timeline同事务；结果矛盾主动查询Commerce。

Outbox至少一次投递，不宣称端到端exactly-once。稳定event_id/operation_id、唯一键、hash和状态条件保证重复不产生第二次业务效果。毒消息保留失败记录，可命令行重驱原ID，不建设完整DLQ管理后台。

## 2. 未知结果

超时/连接断开为UNKNOWN，保持资金预留与行占用。持久对账worker查provider；未查到且可能仍在延迟可见窗口时继续UNKNOWN。确定成功才入已退款账；确定失败才释放。退款成功后没有“本地回滚”。

provider-stub必须持久保存幂等键/请求hash/结果，重启不丢；相同key换金额409。状态NOT_FOUND/PENDING/SUCCEEDED/FAILED，支持成功后丢响应和有限延迟可见。它模拟外部系统，不共享业务库。

重试只有一个负责人；读最多一次短重试，outbox有界退避且持久失败记录；UNKNOWN持续低频查询并在阈值后人工可见，不能为了“收敛”强改失败。

## 3. 简化后的取消/审批

授权未消费：批准、材料更新、撤销、过期都锁case行排序，消费校验当前版本及有效规则。材料更新增revision并撤销未消费授权。

授权已消费：工单不可取消/改输入/换方案；命令已经承诺执行。UI必须明确此边界，接口返回409。不再提供cancel-before-start端点，不能只删实现而保留取消承诺。

确定失败后如要再试，须新revision/方案/授权/operation，旧操作终态保留；UNKNOWN不得走该路径。

## 4. 权限

Gateway剥离伪造主体头，资源服务独立验证JWT、aud/scope以及merchant/customer/line归属。Agent只读工具凭证限定当前run/revision，不可自签、审批或消费授权。模型参数无URL/SQL/shell和凭证。

用户材料/政策/工具正文均为数据；注入文字不能改变工具表或scope。引用hash有效不代表事实真实；Java按固定源重新核验。签名消息仍需验producer/target/schema/payload，不仅看签名存在。

核心授权只允许REFUND；旧兼容Schema可解析RESHIP不等于核心运行允许，新增负面测试必须拦截。

## 5. Agent与回放

PG租约/fence、checkpoint事务校验及稳定调用记录保留。provider结果未落库窗口允许重复计费，不能通过只在安全点杀进程来宣称零重复。调查deadline和预算恢复不重置。

strict回放没有live模型/业务写adapter或凭证，运行环境禁网络。只有实际完整记录可复现；缺项明确失败，不能模拟返回“看起来一样”。

## 6. 精简观测与优化

结构化日志关联case/run/operation/trace ID；低基数指标包括outbox积压、UNKNOWN数、模型usage、工具错误与停止原因。ID不作Prometheus标签，不记录秘密。保留关键审计不依赖采样trace。

只做一个查询路径的索引/非权威缓存对照。授权、金额、退款状态以权威数据复核，不使用展示缓存批准退款。Redis不可用时有界回源，不能击穿成无限并发。

安全/故障验收以evaluation的核心矩阵为准，原F01–F18全量不再是门槛；被保留路径的安全不变量不能用“个人项目”豁免。
