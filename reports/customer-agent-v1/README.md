# 客服Agent / RAG接入证据

2026-10-20。[实施设计](../../docs/customer-agent-implementation-v1.md)，进度仅[todo顶部](../../tasks/todo.md)。本报告将工程接线、脚本模型与真实模型质量分开。

以下按验证批次保留当时结果，早期“尚未接入”不覆盖末节的完整链路证据。

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

## 网页与保留数据整链

网页接通ASSISTANT作者/模式、待处理/生成/失败状态、订单/物流/政策引用、最新回答的可编辑转交摘要和默认不勾选的报告共享。来源按业务文字/事件展示；商家只收确认后的事实/政策报告和客户所选原文。生成期间可纠正或转人工，保留请求幂等/不确定结果重试、历史分页与跨商品隔离。修正已完成回答后仍显示“正在处理”的过时通知。

实际命令为网页`vitest run`（25文件192项通过）、`vue-tsc --noEmit`、`vite build`，最终全部通过。新增三项覆盖回答/引用与共享确认、生成时纠正和转人工、商家报告投影；原有189项保留。Python/Ruff、Java测试和此前平台买家/checkout回归见前节，未宣称全仓所有测试均通过。

备份保留Case后追加Flyway V28；Commerce仍V16，PG使用追加013。临时Case/Commerce关闭原dispatch/消费者/outbox投递/退款派发及对账，仅新咨询派发开启；Python关闭原调查worker/回调，使用显式mock脚本。没有重建政策或embedding，使用既有本地BGE权重和READY generation `bec460aa38d64051a4f5bf13e40c4e83`。网页直连Case，Gateway未重验。

[`scripts/customer_agent_acceptance.py`](../../scripts/customer_agent_acceptance.py)首次成功34次真实HTTP检查，原请求重放最终13次检查通过；[机器结果](runtime-check.json)保存最后一次的逐请求结果/引用hash/代际及保留证明。A-TRANSIT完成物流读取→dense政策检索→回答→确认转交→商家报告，并拒绝别的买家/商家读取；完成run重复POST不新增模型/工具调用。成功run为3次脚本模型、2次只读行动，输出token为mock用量，不作真实成本/节省指标。原8个交易/资金表全表hash、原4个咨询表旧行旧列hash及旧Agent run数量5保持；新增咨询不生成退款Case/授权/槽。

首轮实服务失败原因是验收环境误写`RESOLVEFLOW_POLICY_INDEX=true`，既有配置要求`1`，导致POLICY_INDEX_UNAVAILABLE；脚本仍要求P1引用，被拒绝后脚本耗尽，终态AssertionError。失败run `2a11eaf3-c2e6-47d7-a5cd-628006f6cb6f`及预占/请求均保留，没有清账或换manifest重跑同run。纠正验收开关后客户以新消息形成成功run；这证明检索开关/引用拒绝和接线，不证明真实客服效果。临时启动器对Agent/网页健康检查路径误用也已修正，未改正式启动入口。

[`scripts/check_customer_agent_runtime.cjs`](../../scripts/check_customer_agent_runtime.cjs)真实Edge无头验证[三图](images/buyer-answer.png)、[转交预览](images/buyer-handoff-preview.png)、[商家报告](images/merchant-report.png)，每图1280/1440/1680宽度无横向溢出，共9宽度+2交互检查、0页面异常，[UI记录](ui-check.json)。A-DELAYED通过UI新增一轮明确mock咨询并停留未确认预览，不创建核查单；重跑复用回答。人工逐图检查了字号、勾选框、共享内容、引用和布局，保留图片中的合成/脚本标识。

局限：无新live模型调用/付费评测、无真实用户质量或动态Agent对固定流程的收益结论；无聊天内退款确认/原Case关联；引用校验是身份/来源绑定，不等于全文语义蕴含。核心契约整文件回归80通过、1项既有LineContext可选字段断言失败（payment_version/fulfillment_status/fulfillment_version），该断言与Commerce契约本轮未改，未删除断言。Starlette弃用、Flyway/MySQL兼容及旧Java编译警告保留。旧Gold/量化报告/简历与原四历史脏文件不夹带。

收尾按进程归属关闭design-support-web/design-support-agent/design-case/design-commerce，确认5174/8182/8183/8181均关闭；MySQL、PG、卷和新旧记录保留。最终4咨询/14消息/2核查单、3咨询run（首轮配置失败1+成功2），原Case5/授权4/槽5保持。[完成清单](completion.json)绑定实现/脚本/说明/实图hash与停止记录。三Java正式启动与真实模型联合质量未重跑，本机可按既有入口启动体验，不能把本批mock答案当作真实模型评测成果。
