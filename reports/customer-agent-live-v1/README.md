# 新客服双端真实联调与小样本诊断 v1

2026-10-20。用户授权接续新界面后的真实联调及实际效果测试。本批冻结[8个咨询输入](../../evals/customer-agent-live-v1/cases.json)，共6笔现有模拟订单、两店；使用现有真实模型配置、实际Java/PG/MySQL与本地dense检索，经网页5174→Gateway进入。不是留出集、固定流程对照或生产客服数据，不改旧Gold/简历/量化报告。

## 计划及判定

L01在途；L02签收争议且已排查代收；L03政策插问；L04用户纠正；L05仅人工核查延迟；L06未知；L07查询不可用；L08丢失及政策。逐项检查冻结required条件、原始回答、真实工具结果与引用；语义由Codex结合原文复核，不用模型自评。另在L05显式确认摘要/所选原文/报告，商家补问→客户补充→商家回复→客户确认解决。商家测试回复明确标为本地验收，不冒充真实承运商核查。

先保存原订单/账本/退款/物流、原退款run及政策generation见证。前置核查咨询待办、退款派发、PG旧队列均无待运行任务；只启动所属原数据容器，无清库/新付款/退款/政策导入。启动将复用已构建Java包与现有READY索引。使用现有模型账户执行最多8个新turn，每run沿用12次模型调用/120秒活动预算，不自动扩大或用新请求重跑失败。

驱动`scripts/customer_agent_live_acceptance.py preflight|exercise|collect`：所有写入请求先存忽略目录的原路径/正文/幂等键，恢复复用；已完成或失败turn不作为新turn重测。收集实际model/tool调用、usage及完整答复耗时，失败同样保留。截图使用实际网页与业务接口，无API拦截；页面行为和模型质量分别报告。聊天内退款确认尚未实现，本轮不测其完成率。

## 前置结果

`ruff check --config agent/pyproject.toml`及format、Python编译/CLI检查后提交冻结输入与驱动。准备中纠正了账本表名及AssistantTurn协议定位：使用实际run_id等待结果，未向业务模型发送请求。原四历史脏文件保留。

## 实际结果

**真实联调已完成，业务效果仍有两处缺口。** [完整原始结果](runtime-results.json)保留实际输入/历史、模型动作及usage、工具观察、回答和确认后的商家投影；[逐条源审](semantic-review.json)记录判定与原因。22次真实模型请求，8/8 run生成回答；场景目标6条通过、1条不通过、1条故障场景未有效覆盖，不以run成功冒充任务成功。

| 输入 | 实际结论 |
| --- | --- |
| L01 在途 | 通过；查询物流，不重复索要编号，不编送达日期 |
| L02 签收争议 | 通过；保留陈述冲突、采用已有代收排查，引用签收规则并等待确认 |
| L03 政策插问 | 通过；本店版本及R-SIGNED-001准确，不创建申请 |
| L04 纠正收到 | 通过；采用最新陈述，不继续旧核查摘要或退款 |
| L05 延迟+人工 | 通过；实际确认摘要/一条原文/调查依据，商家补问→客户补充→商家回复→客户解决，其他店/买家读404 |
| L06 UNKNOWN | 通过；区分未知与未发货/丢失，系统交接问题交商家核实 |
| L07 查询失败 | 覆盖缺口；客服工具读到正常履约投影，未触发预期503 |
| L08 LOST政策 | 不通过；漏关键丢失条件，引用无关条款，混用订单/物流状态 |

固定范围内模型实际usage合计输入29,677、输出2,007 token，全部由provider返回、estimated=false；共14次只读工具/检索行动。总费用未按未经核验的单价换算。8turn完整HTTP答复耗时2.158–65.325秒，中位5.1965秒；首个政策检索在tool开始到下一model开始间约59.1秒，其余turn约2–6秒。该停顿发生在本地首次dense检索阶段，冷加载因素需后续剖析，不全部归给模型服务，也不据8个样本宣传稳定p95。历史中含既有mock/人工记录（L02的未授权代收来自原文），本轮是真实模型+合成业务数据诊断，不是新独立数据集。

## 两处具体问题及后续顺序

**物流故障接线。** [只读诊断](diagnostics.json)证实B-QUERYFAIL的原shipment接口确实返回503，故障记录保留。客服`SupportAgentTurns.fact(shipment)`却调用`shopping.fulfillment`；`MerchantTradeService.fulfillment`直接读取shipment表，未经过`ShipmentReadService`的故障检查，返回正常IN_TRANSIT。因此本例不能评价模型如何处理503，先修工具读取语义及确定性测试，再测真实失败体验。未关闭故障开关，也未修改物流。

**RAG及回答适用性。** L08实际query为“台灯 物流确认丢失 本店政策 后续处理 条件 补发 退款”，包含用户未要求的补发。正确R-LOST-001原文存在于本店同一READY generation，但dense排第4，被Top-3裁掉；固定同query/同generation的离线BM25也排第4。模型没有再次查找主条款，引用普通在途、损坏、未发货规则解释丢失，且将SHIPMENT的LOST称为ORDER状态，真实订单为PAID。先处理查询聚焦、关键条件召回/生成适用性，不把单次排名当部署融合重排依据。本批只诊断，未修改Agent提示词、召回参数或生产路径，失败输入/输出不覆盖。

## 真实网页核验

[浏览器记录](ui-check.json)：真实5174→Gateway→Java数据，无API拦截或预置响应。5图×1280×800/1440×900共10视口，加政策原文展开、真实订单弹层跨店切换/恢复、商家共享投影/实际接续及解决后输入禁用三项，共13通过，0页面异常/0业务HTTP错误。浏览器核验未发新模型消息，API驱动才执行上述8turn；不能称全部问题由UI逐条发送。实图均逐张核看，失败场景也保留：

- [在途真实回答](images/buyer-l01.png)
- [政策原文展开](images/buyer-l03.png)
- [查询故障未贯穿的实际回答](images/buyer-l07.png)
- [丢失场景的错误政策回答](images/buyer-l08.png)
- [商家实际接续](images/merchant-followup.png)

## 验证与收尾

实际命令：`customer_agent_live_acceptance.py preflight/exercise/collect`；`customer_agent_live_diagnostics.py`只读对照；`node scripts/check_customer_agent_live.cjs`无API拦截，Node通过现有NODE_PATH解析Playwright。两个Python脚本Ruff check/format、py_compile和Node语法检查通过；模型输出/商家投影再用现有核心契约校验，结果见[完成清单](completion.json)。原前端201项未重复跑，页面/后端/Agent生产源码本批未改。

启动实际顺序为保留MySQL/PG→核查旧待办→复用现有Java包/受控容器→`start.ps1 -SkipBuild -NoBrowser`复用健康Java并启动真实Agent/网页，9组件检查通过；没有执行prepare中的政策重导入/索引replace。collect比对13份原交易/物流/退款run/政策generation全行hash均保持，新增仅咨询及人工接续记录，未创建新购买或退款。收尾恢复本批前关闭状态，`stop.ps1`保留数据卷；最终端口/图片/源码hash与Schema检查见完成清单。原四历史脏文件和旧资产不夹带。

当前可称“新双端真实接线及首轮质量诊断完成”；不能称客服全部效果达标、正式量化对照完成或聊天退款衔接完成。下一步优先修上述物流读取和RAG缺口，再冻结针对性新结果，本轮证据保持。
