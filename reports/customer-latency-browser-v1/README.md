# 客服页面收尾验收

2026-10-24，浏览器控制恢复后接续原两项体验收尾。生产源码仍为64723e6所含05801d9版本；不再追加服务端付费队列，不修改业务实现。

正式`start.ps1 -SkipBuild -NoBrowser`保留原卷启动，全部组件/精确政策索引健康。启动前Case待处理/dispatch及PG QUEUED/RUNNING均0，启动未发送模型请求。

先零模型刷新旧buyer10/E10EE1会话：实际页面已恢复原已编辑原因和补充文本，见[观察](old-draft-reload.json)、[AX](old-after-reload.txt)和[截图](old-draft-restored.png)。卡片实际为“请重新核对”，不是可直接确认的当前草稿；保留该事实，不将旧版本恢复等同新草稿确认状态验收。

接着[冻结计划](plan.json)中一个新合成LOST订单/空会话，只发一条咨询，最多原run预算12次模型请求；使用CUA逐次只读渲染文本采样，不注入fetch拦截或伪造流式。保存中间文本/最终回答，再编辑原因、保存、刷新；不点确认/转交、不创建Case/退款。独立计量进程持有原usage账本锁，失败同样收集持久模型调用，先UUID规范化再计账。

准备验证：新驱动Ruff、py_compile通过；旧页面恢复完成，新咨询与渐进正文尚待执行。新样本创建使用既有已测API准备器，模型请求0，usage2375；本页不是简历统计或独立盲测。

## 实际结果

准备35e5488已普通push核实后执行一次。CUA实际读DOM确认6个不同的中间正文；[逐次观察](dom-observations.json)记录首反馈316ms、首正文5596ms、完整回答7210ms，包含工具与浏览器采样开销，仅一例观测窗口，不是精确首token或p95。Java持久事件另记首delta5429.744ms、commit6988.503ms，自turn.accepted算；16个answer.delta、reset0，模型两段解释在最终回答中均保留，程序在段间/末尾插入事实字段，不能称最终字符串与流式全文逐字相等。

[新页面结果](ui-results.json)：自动退款原因将用户原话与系统ORDER/SHIPMENT记录分开；¥329.00正确，编辑加入补充后保存，刷新后原因逐字一致，仍有“待你确认”和“确认提交申请”。[卡片上半](new-draft-card-top.png)、[刷新后补充及确认按钮](new-draft-restored.png)、[实际对话](conversation-overview.png)、[中间流式](stream-intermediate.png)均为CUA实际截图。未点击确认/人工转交。旧草稿“请重新核对”根因为已过expires_at；[只读数据库观察](backend-observations.json)同时保留到期时间与服务器UTC时间，原因内容并未丢失。

[逐项源审](source-review.json)：本例业务诉求满足，真实UNDERSTAND→READ_FACTS（含模型policy_query）→RESPOND共3模型调用，ORDER/SHIPMENT/GUIDE/本店6条政策均真实读取。解释保留LOST且无有效签收/人工核验前提，不把草稿当审批。不宣称回答质量全面冻结：正文偏长，两个事项装配重复物流字段，已有卡片时程序教程仍写先点“申请退款”，上下文指引不够精炼；有效签收验证仍留人工，不能将模拟事件流冒充真实承运核验。

**本批页面功能通过，首正文4秒目标未通过。** 不追加收费追题或更换架构。两版服务端复杂目标仍各1/2，本例网页首正文5.60秒，保持原失败；3模型请求不代表Java真实接口/前端与固定HTTP快照队列耗时相同。后续若用户继续优化，优先基于现有时间线分解模型理解/决策/首内容及业务往返，而非重跑刷分或为该问句加特例。

计量进程仅持锁等待CUA，finally读取实际journal计账：1个SUCCEEDED客服run/7条调用（3模型+4工具），10713输入/558输出，未知/估算0，usage2375→2378。与前两版共19真实请求、62703输入/2939输出，合计仅作计量，不作独立样本效果指标。[运行计量](runtime-results.json)的backend_checks_passed为真，初始success字段保留false，不能据该计量占位字段判UI或整体质量；综合功能判据见[总结](summary.json)。

[保护审计](final-audit.json)：旧Case/归属/政策/授权/支付/退款和旧run/索引保持，公共PG仅新增1客服run/7call，其余9表hash保持，188历史报告/10保护文件/9冻结源码保持；新单支付32900/已退0/预留0，无Case/核查/授权/退款。原草稿revision2/input_version3及原因保持，新草稿同为revision2/input_version3、case_id NULL。实际供应商密钥扫描通过，账本锁释放。本批stop.ps1停止所属5进程/5依赖容器，卷保留、Docker仍运行；无全仓测试或简历修改。

实际命令：`start.ps1 -SkipBuild -NoBrowser`；新脚本`ruff check`/`py_compile`/`prepare`/`watch`；CUA真实登录、一次发送、只读连续采样、编辑保存及reload；只读来源/保护核验；`stop.ps1`。第一次打开页面时Web尚未启动，ERR_CONNECTION_REFUSED，正式启动健康后新建标签正常；一次辅助检查访问不存在的failure_code键失败，随后按实际字段只读核对，未重发/改模型结果。未运行全仓、审批/执行退款或多轮泛化验收。
