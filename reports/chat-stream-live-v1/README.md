# 完整客服流式小规模真实验收（2026-10-23）

## 固定范围

用户批准S3工程完成后的集中真实验收。生产基线d4836e7，三个Java服务、Python AgentScope staged-v1、DeepSeek Flash、本地真实政策索引、Vue和Edge全部实际连接；不拦截API、不用脚本模型。已有A-DELAYED合成订单沿用，不改订单/物流/政策、不创建退款或人工核查单，不是独立盲测或简历指标评测。

[冻结计划](plan.json)预先固定三条连续问题：物流咨询、政策和材料解释、已找到包裹后的诉求纠正。每轮沿用生产12次模型/30秒边界，三条最多36次模型尝试，不自动重试失败回合。第二轮在收到实际turn.started后刷新页面，检查只读恢复和无重复用户消息。原用量账只追加实际持久化尝试，未知响应单列；不重置历史次数，不把有限样本当p95。

## 准备与命令

- 只读预检：Java客服无PENDING/RUNNING、原调查无PENDING，PG调查无QUEUED/RUNNING、客服无RUNNING。原四个未提交文件保留。
- `JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1`，`./start.ps1 -NoBrowser`：重新构建当前Java，原数据与精确政策索引复用，全部组件状态通过；启动不执行测试模型请求。
- `agent/.venv/Scripts/python.exe -m ruff check scripts/accept_support_stream_v1.py`、`-m py_compile scripts/accept_support_stream_v1.py`、`node --check scripts/check_support_stream_live_v1.cjs`通过。
- `agent/.venv/Scripts/python.exe scripts/accept_support_stream_v1.py prepare`：冻结输入/源码SHA及私有before快照，无模型请求。执行：同脚本`execute`。该命令通过账锁启动真实浏览器并在finally采集调用/用量/业务表保持证据，已有执行标记禁止重发。

## 结果

首次执行失败，见[browser原记录](browser.json)和[运行原记录](runtime-results.json)：第一条发送未启动Agent，等待75秒后停止，无新增run/模型调用，usage2012保持，业务表hash保持。根因是A-DELAYED已有RESOLVED人工核查单，页面默认收件人为商家；脚本未选择“询问智能助手”，不是模型失败。该记录保持原文。修正脚本显式选择助手、HTTP错误提前结束和独立结果目录后，原三轮输入转到v2继续，未重试任何真实模型结果。

首正文按点击发送至DOM首次真实候选正文；完整回答按DOM正式消息出现（40ms轮询和截图开销会影响完成时间），SSE提交时间另存原事件；两者均不是单独Provider首token。页面刷新会造成观察空窗，第二轮须单列解释。

补充：首次误发实际新增1条发给商家的咨询消息，并使已有核查单回待处理，原记录保留；“业务hash保持”仅指快照中的资金/订单/物流/政策/原调查表，不含咨询表。30秒为模型单请求timeout，Java run活动窗口实际120秒。三轮最终证据和未完成项见[v3汇总](../chat-stream-live-v3/README.md)。
