# ResolveFlow 七条简历：本轮量化实验

2026-10-07。按用户确定的[协议](../../docs/resume-quantification-plan.md)整批执行。所有成绩来自本轮原始记录；现有架构证据单独关联，不将历史测试冒充本轮新测。该报告用于个人项目面试，数据为冻结合成业务案例/工单与已有外部原文查询；Agent与恢复使用真实LLM，退款使用持久模拟支付。

| 技术点 | 本轮测量及结果 | 可复算证据 |
| --- | --- | --- |
| 1. 多租户微服务 | Gateway、Case、Commerce、Python Agent；主体隔离、购物车版本/行锁、多行原子付款与逐行退款。此条展示设计，不新增规模数字 | [实现入口](#架构与事务证据)、[原闭环](../product-flow.md)、[多行资金](../multiline-refunds.md) |
| 2. Agent自主调查 | 32场景×两组×两次=128调查；有效建议固定62/64、动态56/64；复杂50/52 vs44/52。HTTP读取192→159，模型137→300 | [报告](agent/README.md)、[128条复核](agent/cases.md)、[summary](agent/summary.json) |
| 3. RAG | 外部29查询五组；17完整可答，BM25→rerank Recall@3 85.78% vs BM25 81.37%，前三完整13/17 vs12/17。商城54正例Recall@3 98.15% vs dense93.52% | [报告](rag/README.md)、[外部](rag/external-v2.json)、[商城](rag/mall-v1.json) |
| 4. 版本化授权 | 8类80轮，90/90过期尝试拒绝、80/80当前有效控制消费、非法消费0；另10/10消费先提交后输入更新拒绝 | [报告](authorization/README.md)、[summary](authorization/summary.json) |
| 5. 可靠退款 | 6类60故障全部通过、70行各一次成功；重复成功/超额均0、UNKNOWN原操作查询10/10收敛 | [报告](refund/README.md)、[矩阵](refund/formal-v1/results.json)、[summary](refund/summary.json) |
| 6. Harness恢复/回放 | 3窗口15对/30真实崩溃，续跑两组各15/15有效；新增模型61→51（-16.39%）、token101937→89486（-12.21%）；strict18/18 | [报告](recovery/README.md)、[逐对](recovery/formal-v1/results.json)、[summary](recovery/summary.json) |
| 7. SQL/Redis | 20000工单、4000待审、2商家；18正常窗口，30并发p95中位数63.9→18.9ms、DB查询/成功请求减少99.76%；12故障窗口实测Mapper峰值8，超时拒绝率中位数42.50% | [报告](review/README.md)、[30窗口审计](review/audited-summary.json) |

## 结果如何用于简历

Agent在此固定业务包上没有优于固定流程，删除预设的准确率和复杂处理提升句。可以写动态调查实现、32场景128次真实对照、87.5%有效建议以及业务HTTP读取减少17.2%；更少HTTP读取没有抵消更多模型请求，不称整体降本。RAG展示已实际接入实验的重排质量收益；生产默认dense未改，两组Agent实验共用C，外部rerank平均2.22秒、商城0.55秒的延迟成本保留在详细报告。

授权按尝试数90、当前有效控制80报告；80是8类各10轮，不是80种竞争。退款60故障是重复轮次，成功交易计量按70个订单行，不按重投消息计数。恢复15对使用1个业务场景、3种故障窗口，不写成15个不同业务问题；中断后的请求和token为收益分母。性能使用成功请求p95、错误率及每成功请求实际Mapper查询数，索引和缓存收益分开。

## 架构与事务证据

以下是现有实现的只读定位；本轮不重复全仓回归、不新增架构吞吐量承诺。

- [核心范围](../../docs/core-scope.md)：三个Java进程+Python Agent，Agent只读建议，Java拥有授权与资金，模拟外部支付与物流。
- [CartService](../../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CartService.java)：按merchant/customer购物车主体、revision检查及购物车/商品行锁。
- [MultiCheckoutService](../../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/MultiCheckoutService.java)：同店多行快照、幂等草稿、价格/版本复核与混店拒绝。
- [CheckoutPayments](../../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CheckoutPayments.java)：付款结果持久后同事务发布订单行、行退款槽与整单账本，初始NOT_SHIPPED独立于退款。
- CaseScopeEnforcementTest、InternalScopeEnforcementTest及既有[业务闭环](../product-flow.md)的跨客户/跨商家404证据；本轮授权/退款另有真实HTTP/MySQL验证。
- [本轮资金反例修复](refund/fixes/README.md)：同操作竞争current-read重查，实际HTTP EOF转UNKNOWN；集中28项通过后执行60故障。原四个用户脏文件始终保留，不夹带提交。

## 执行与复算

详细报告包含实际命令、资源、原始记录、输入/源码hash、计量分母、失败/跳过及没有运行的验证。开发试跑失败保留且不进入正式分母；Agent正式所有失败计入64次，按原始响应复核而不追加付费刷分。模型usage累计账本不重置；无新资源购买、公网发布或真实支付。

离线复算入口：`scripts/resume_agent_summary.py`、`scripts/resume_authorization_summary.py`、`scripts/resume_refund_summary.py`、`scripts/resume_recovery_summary.py`、`scripts/resume_review_summary.py`。RAG原逐query计量及排名直接在JSON；SQL/Redis完整采样压缩保存。`scripts/resume_quantification_summary.py`核验各批完整性、原始记录/源码/权重hash及最终文案，生成[完成清单](completion.json)。正式Agent与恢复合计579次真实模型请求，开发试跑另存、不计正式分母。最终七条表达见[简历文案](../../docs/resume-seven-points.md)，桌面量化实验版PDF已同步填数，原简历保留。
