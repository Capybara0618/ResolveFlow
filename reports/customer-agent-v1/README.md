# 客服Agent / RAG接入证据

2026-10-20。[实施设计](../../docs/customer-agent-implementation-v1.md)，进度仅[todo顶部](../../tasks/todo.md)。本报告将工程接线、脚本模型与真实模型质量分开。

## 咨询循环与来源适配

新增Python support/protocol.py、engine.py与sources.py，AgentScope Agent驱动READ_TOOL/SEARCH_POLICY/ANSWER，复用现有AgentScopeModelAdapter/ModelClient/BudgetGuard/输入计数及PolicyIndex。模型自主选择读取/检索，咨询不创建虚假Case/退款方案；订单、物流、历史只走绑定咨询run的Case facade。政策采用dense及商家/bundle/manifest/generation前置过滤，不回退其他租户或BM25。

新单元19项通过：动态物流/政策选择、无需强制搜索、拒绝写工具/身份覆盖/假引用、预算/过期/超长、查询失败、完整实际输入计数、HTTP来源失败/旧输入及检索过滤。全部模型为明确mock，不能作为客服质量分数；Java/API/PG/网页连接和真实dense验证由后续本批步骤完成。

红测因模块不存在失败；首版工具停止异常触发SDK已安装MCP异常别名问题，改为工具错误观察并在下一模型调用前终止，未修改SDK或安装依赖。来源适配首版误用旧异常类名、测试导入路径及Ruff排序已修正；日志保留忽略目录`tmp/customer-agent-design-v1/assistant-*`。当前引用验证证明来源存在/绑定，尚不等价于每句自然语言均被引用语义支持。

本步骤未调用付费模型、未运行后台worker或修改现有数据/简历/Gold；生产旧Case循环与协议保持原实现。正式接线前还需PG调用账与旧输入发布验证。

## PG调用账与内部咨询API

追加PG 013支持独立咨询run/call；输入/manifest/deadline不可变，领取带180秒lease与fence，所有调用预占/保存与终局重新校验fence。完整模型/工具调用可重放，未完成调用保留预占并报UNKNOWN/INTERRUPTED，不静默补付或清零。内部同步咨询接口供Java异步调度调用，不新增Python居民循环；要求case-service、support:run和相符商家/客户，读取凭据仅留在请求内存，不写调用账。

保留演示PG启动、无旧调查worker。5项真实PG隔离schema测试覆盖完成复用、并发拒绝、manifest/fence、未完成调用预占、已保存模型结果后崩溃重建且0新增模型/工具调用，以及真实PolicyIndex接口的dense候选（此项embedding为明确stub，不当真实向量效果）。补查实际Index API发现require_ready返回generation对象列表，已修正咨询适配并以真实索引测试，而非只靠mock签名。

新API/协议根对象封闭，新增Agent核心路由1项（7→8）与请求/结果/错误3组件、合成fixture，保留旧路由断言。新增API单元证明错误scope/主体/绑定拒绝、无假Case字段与token不入运行输入；完整新批测试与本地契约引用检查命令/计数在账本顶部。开发红测缺store模块，格式/导入问题已修复；既有Starlette测试弃用警告保留。Java/网页尚未接入，不据此宣称客服可用或真实质量通过。

## Java咨询派发与确认共享

Case追加V28：客户发送给助手的消息在原事务中生成独立咨询待办；后台单工作线程调用Python，HTTP在本地事务外。冻结商家/客户/商品、支付时政策版本和当前原文；每个run的只读JWT仅有support:read，绑定输入版本/fence，不能读其他run或调用原退款工具。回复入库前再次核对身份、版本和fence。修复旧派发者不得将新fence标为STALE的并发问题。

助手消息含模型模式、引用和转交摘要；客户明确确认assistant_message_id后才复制订单/物流/政策依据给商家，对话历史引用不自动共享，仍由客户选择原文。不创建退款Case或授权。独立开关resolveflow.support-agent.enabled可只启咨询派发，默认沿用原dispatch开关；便于保留数据验收时关闭原调查及退款后台。

JDK21实际命令：`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=SupportApiTest,SupportWireTest,SupportCredentialTest -Dsurefire.failIfNoSpecifiedTests=false test`，最终Case13、共享Wire2、凭据1共16通过/0跳过；此前含平台买家8和checkout4的回归也通过。新增契约/共享fixture及引用/重复路由检查22通过，Case79→81。Spotless限定本步Support/JwtCodec/ServiceTokenFilter文件通过。此阶段使用Testcontainers隔离MySQL，未迁移保留业务库、未调用真实模型。

开发过程修正过YAML片段生成导致的重复alias，未放宽旧Schema断言；最终重建仅Support组件块并验证。PowerShell Maven含点参数必须完整引用，首个package命令误拆参数失败后按原命令修正；不会将构建失败写为通过。Python类型补齐与网页接线另验证，不把工作区尚未提交部分算本步依赖。

## 咨询模块类型与SDK签名

新support七个源文件补齐函数/容器类型，PG可空行显式检查；AgentScope工具check_permissions改为实际SDK要求的async接口并提供message，未修改SDK。`python -m mypy --config-file agent/pyproject.toml agent/src/resolveflow/support --follow-imports=silent`实际7文件通过，无关闭错误类型或新增全局豁免；早期skip导入的辅助结果不作为正式门禁。Ruff check/format通过。真实PG隔离schema+新API/来源/循环最终25通过/0跳过；此前含契约共43通过。首次误设测试DSN造成5项跳过，改用现有RESOLVEFLOW_AGENT_DB后重跑，未把跳过计通过。所有模型mock，本地测试不作质量分数。
