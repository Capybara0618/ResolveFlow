# 当前客服真实等待分解

2026-10-25，按用户要求回到Agent等待主线。采用当前a51fbec中包含15aaab2的生产实现，先按[本批说明](../../docs/customer-wait-profile-live-v1.md)冻结一个新合成订单/空会话和原物流+退款原因问题；[计划](plan.json)最多12新模型请求，只发一次，不确认建单或人工转交。

准备：原队列四类均0；正式`start.ps1 -SkipBuild -NoBrowser`复用原数据与精确政策索引，计数器启动预热360.962ms、embedding/BM25预热31388.657ms单列，之后才READY，预热0生成模型。新准备wrapper复用既有已验证prepare/watch/usage锁及保护核验，不另写计量协议；Ruff通过，准备创建本轮合成购买/物流和空会话，0模型，usage2378。

源码/输入精确commit普通push核实后，通过CUA一次发送并采样实际DOM，将同run生产日志与持久事件对齐。当前未发送新咨询，不能将准备就绪当效果通过。旧真实数据和成绩保持，单例只定位当前关键路径，不作稳定SLA或简历指标。

## 实测结果

准备d310e7d普通push核实后，仅发送冻结的一条问题。真实Vue→Gateway/Case→Python/DeepSeek→原PG/本店政策，一次3模型调用，无修正追题；输入10706/输出545、usage准确、未知/估算0，账2378→2381。[计量](runtime-results.json)、[页面逐次采样](dom-observations.json)、[界面结果](ui-results.json)、[逐项源审](source-review.json)。运行计量保留初始success=false占位，backend_checks_passed=true；本批业务/页面是否通过按源审和观测判断，不借该占位字段计分。

页面首反馈307ms、首正文3970ms、最终5340ms，观察到5个不同中间正文；Java持久首delta3627.908ms、commit5158.096ms，自turn.accepted算。页面与服务端起点/时钟/采样不同，不能直接相减当精确前端耗时。本例4秒样本目标通过但仅余30ms，不能称稳定达标或归因某项改动；前轮5.60秒保留，不算随机成对提升。

| 实际阶段 | 供应商调用全程 | 其中首JSON内容 |
| --- | --- | --- |
| UNDERSTAND | 1198.529ms | 276.897ms |
| INVESTIGATE | 810.829ms | 405.553ms |
| COMPOSE | 2121.373ms | 495.444ms |

完整数值见[时延分析](timing-analysis.json)及[精确run日志](phase-timings.log)。模型调用合计4130.731ms，约占服务端commit时间80%；本地三轮prepare合计约107ms，当前性检查约48ms、模型journal起点约20ms。订单源23.663ms、物流29.639ms、政策22.044ms；政策内部source_total21.675ms。**本例主要等待在串行模型调用，不在政策读取**。这里本店只有6条政策，实际采用COMPLETE_SMALL_SET，不能把22ms套成所有大语料RAG/重排的速度。

第一模型journal距离turn.accepted仍有596.025ms；现有细分日志没有覆盖该整段初始化/调度，不能把它全算TLS或加载。COMPOSE从journal到可读首delta672.282ms，其中首JSON内容约495ms，剩余包含JSON字段前缀/投影/投递，不能称供应商已经在495ms产出了完整可读正文。TLS、排队、prefill/decode在现有provider_ms中仍不可细分，不编造根因。

本例业务完整：读当前订单/物流并自主携带policy_query，解释LOST且无有效签收、人工核验与未核实处；退款卡片金额329元、DRAFT rev1/input_version3、case_id NULL，未确认/转人工。两段模型解释最终保留，15条delta、reset0。之前两个程序装配缺陷在实际页面也已消除：物流事实块1处、不再要求先点“申请退款”，采用卡片准备后的核对指引。模型自然语言仍复述状态、政策说明偏长；这与“程序事实块跨事项重复”不同，未声称语义重复已全部消失。摘要只包含其事项ORDER事实，物流由另一事项读取，未偷跨事项扩大摘要来源。

## 工程取舍和收口

当前不为这一单例改三阶段架构、删除必要理解/政策、强制工具路径或追加付费题。已确认的本地冷加载和确定性呈现优化保留；下一次若继续压等待，应先细分接收至首模型约0.60秒初始化/调度，再评估紧凑理解输出或更短解释的质量取舍，不能把模型服务波动归为RAG故障。首正文可用性较前轮好，但仅本例通过，框架可保留，不作全面质量/性能冻结。

[最终保护审计](final-audit.json)：旧业务、旧客服run/政策索引、188历史报告、全部冻结来源及原四脏文件保持；公共PG仅新增本run/7call，其余9表hash保持。新订单实付32900/已退0/预留0，无Case/核查/授权/退款/通用调查；实际供应商密钥扫描通过、usage锁释放。结束正式stop仅所属进程和依赖，原卷保留、Docker留运行，项目关闭。无额外服务端队列、简历更新或全仓测试；新wrapper Ruff通过，业务实现本轮未改。

实际命令为正式start -SkipBuild -NoBrowser、新wrapper prepare/watch、CUA一次登录/发送/连续只读DOM观察、按run摘录计时及SQL只读审计、stop.ps1。真实截图：[用户与客服对话](conversation.png)、[最终卡片](answer.png)、[生成中](streaming.png)。
