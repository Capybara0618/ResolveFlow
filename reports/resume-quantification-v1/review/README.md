# SQL/Redis：2万工单HTTP测量

2026-10-07。独立MySQL schema resume_review_20261007a，20000工单、4000待审、2商家，真实Case HTTP/Mapper/Redis。合成热点分布80%商家一首页、10%下一页、10%商家二首页，seed42；三条件各10/30并发、3轮，每轮30秒预热+60秒测量，轮换顺序。成功响应逐请求验证20个确切case_id、游标无重复/跨商家及客户403；每轮先等缓存TTL后单独保留3次冷缓存读取，不计稳态p95。

| 并发 | 条件 | 成功p95三轮中位数ms | 成功RPS中位数 | DB查询/成功请求中位数 |
| --- | --- | --- | --- | --- |
| 10 | 原索引/缓存关 | 34.060 | 548.95 | 2 |
| 10 | 复合索引/缓存关 | 21.774 | 1366.14 | 2 |
| 10 | 复合索引/缓存开 | 17.749 | 1717.93 | 0.004520 |
| 30 | 原索引/缓存关 | 63.873 | 717.68 | 2 |
| 30 | 复合索引/缓存关 | 20.319 | 2112.67 | 2 |
| 30 | 复合索引/缓存开 | 18.949 | 2287.61 | 0.004827 |

30并发复合索引自身p95收益约68.2%，其上缓存额外减少约6.7%，组合减少约70.3%；缓存DB查询/成功请求由2至0.004827，减少99.7586%。按相同并发3轮各自指标取中位数，不能把最好的单轮或不同并发拼接成前后值。每个返回页通常2次Mapper查询（队列+requested actions），计数位于实际Mapper处。

正常窗口错误率中位数都是0，但第二轮10并发cache有1次URLError(status0)，保留于102588次请求分母；没有补跑该失败或称整个批次零错误。旧负载客户端对transport异常使用3000ms超时标记，此值不是实测失败时延，正式p95只取成功请求；Redis故障执行器专门记录实际transport失败耗时。缓存值不是授权来源，审批/金额仍查数据库。

## Redis故障回源

专用TCP代理56380→既有Redis56379，只切断/阻塞自己的连接，不停共享Redis、不清共享cache。四类：热点2秒TTL到期、断连、100ms命令超时、断连解除后恢复；32并发、10秒预热/30秒测量，各3轮共12窗口。Semaphore=8、等待100ms。peak取实际Mapper调用AtomicInteger峰值，统计范围为本进程启动至窗口结束（包括验证/预热/测量）；不是拿配置8作为观测值。

12窗口已完成，三轮指标分别取中位数，Mapper峰值取三轮最大值：

| 场景 | 成功RPS | 成功p95 ms | 拒绝率 | 失败p95 ms | 实测Mapper峰值 | 三轮拒绝总数 |
| --- | --- | --- | --- | --- | --- | --- |
| 热点TTL到期 | 2207.07 | 19.526 | 0 | 无失败 | 8 | 0 |
| Redis断连 | 2066.50 | 22.162 | 0 | 无失败 | 8 | 0 |
| Redis命令超时 | 72.25 | 326.908 | 42.50% | 232.273 | 8 | 4843 |
| 断连解除后恢复 | 2081.69 | 21.932 | 0 | 无失败 | 8 | 0 |

故障共586379次请求、4843次失败，逐请求核对全部为503且与实际fallback_rejected计量一致；每窗口结束inflight为0。超时窗口成功RPS明显下降：回源许可持有期间还会遇到缓存写入超时，等待许可超限后返回503。因此此实验支持有界回源和恢复行为，不支持“Redis异常无损可用”。正常18窗口共1578938次请求、1次transport失败，失败保留。

受控阻塞数据库另有本轮ReviewQueueBackpressureTest 2项通过：真实阻塞8个Mapper调用、12并发中4拒绝、释放后inflight回到0。该受控测试与自然HTTP故障窗口分别报告，见[授权批次](../authorization/README.md)。完整[审计汇总](audited-summary.json)绑定30个压缩原始采样与执行来源。

## 运行及资源

[环境](environment.json)记录Windows/Ryzen9 8940HX 16核32线程、16GB、Java21.0.12 JVM256/768MB、Docker服务无独立CPU/内存限制、Redis100ms连接/命令timeout。所有负载client/Java/MySQL/Redis共享本机，PG及MQ依赖全程闲置不变；LLM/退款任务先结束，无重叠。一次短暂本地简历xelatex编译/渲染发生于故障第二轮，未与18个正常性能窗口重叠。缓存TTL2秒，各轮独立namespace；schema仍保留，未清业务库/卷。结束后所属Case进程与TCP代理已停止。

正常命令：`python scripts/resume_review_benchmark.py --schema resume_review_20261007a --output reports/resume-quantification-v1/review/normal-v1 --prepared`。会话在17个完整窗口后被中断，第18个无结果；保存[中断前launcher](normal-v1/launcher-before-interruption.py)、[17份hash及说明](normal-v1/interruption.json)，用`--continue`逐份校验并仅重测缺失的r2-indexed-c30，完整30/60秒。旧17份字节不变，未根据成绩重新选择样本；生产jar、负载client与配置未改变。执行器增加续接逻辑而非改测量路径。

故障命令：`python scripts/resume_review_faults.py --schema resume_review_20261007a --output reports/resume-quantification-v1/review/fault-v1`。正式前[只读PING冒烟](proxy-smoke.json)验证正常PONG、断连、真实超时和恢复PONG，未当性能分数。`python scripts/resume_review_summary.py`读取18+12压缩采样，核对完整计量/来源hash/实际Mapper峰值后生成audited-summary；无网络或负载。原始每请求status/正确性/时延都保留，故障成功与失败时延分开。

本批只在隔离schema轮换已有index，生产默认设置不改；原四用户脏文件及旧报告保留。
