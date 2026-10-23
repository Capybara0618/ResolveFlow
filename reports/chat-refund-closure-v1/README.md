# 聊天退款闭环实施验证

2026-10-23。范围与预期图见[实施合同](../../docs/customer-chat-refund-implementation-v1.md)。本报告区分隔离MySQL/HTTP、合成页面和真实模型，不改旧量化结果。当前进度只见tasks/todo.md顶部。

## R1 草稿

新增V31、SupportRefundWire、SupportRefundService/Controller；草稿30分钟持久化、可编辑/取消/恢复，金额/数量来自本人订单行。会话输入变化后显示STALE，过期显示EXPIRED，不建Case、不调用模型；私有入口仅本人平台买家，商家沿现有工单处理。

实际验证：在java目录设置JAVA_HOME为既有JDK21，`./mvnw.cmd -B -pl case-service -am -Dtest=SupportRefundApiTest,SupportRefundWireTest -Dsurefire.failIfNoSpecifiedTests=false test`，真实临时MySQL/Flyway/HTTP **31通过、0失败/跳过**（包括28项继承咨询回归），共享DTO **1通过**，reactor53.016秒；Commerce为显式作用域stub，无真实模型。根目录`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_support.py agent/tests/unit/test_contracts_support_refund.py agent/tests/unit/test_contracts_openapi.py -q --tb=short` **110通过/19.55秒**。`-DspotlessFiles=.*SupportRefund.*\.java spotless:apply spotless:check`仅格式化本步5Java文件，通过；git diff --check通过。

失败保留：首条红测实际404，1失败；实现后31项中1失败，定位幂等同body的JSON树Long/Int节点类型差异，改为双方都序列化后读取再比对，原断言不改，最终全通过。两次格式命令误用glob而插件要求正则，明确失败后改为正则通过。OpenAPI写文件换行曾产生全文件diff，已恢复原LF，仅新增路径/schema。未启动原数据库/Java/Web，没有新Provider调用或正式退款执行。R2确认/原子建单与R3页面尚未在本步实现。

提交后补记：R1暂存差异检查发现新JSON fixture为CRLF，命令串未在失败处终止而继续提交。现已单独恢复LF并重新检查；不改任何fixture值或测试结果。后续提交显式检查退出码再继续。

## R2 确认与原子建单

CaseService拆出只读准备，旧create仍复用原CaseWriter。确认外部资格/金额和政策读取在事务外，账号/绑定/会话/草稿复核、原Case/run/政策/行槽/幂等及会话关联在同一短事务；已有申请也保存确认回执。确认恢复不需要模型，既有异步退款调查保持。客户状态使用原CustomerCaseService.Detail。

红测确认路由404，1失败。实现后Case45项1错误：测试触发器需要MySQL SUPER权限，改为临时测试表CHECK约束注入确认写入失败，仍验证Case/run/幂等全部回滚；未改生产权限。修正后完整相关Case **47通过/0跳过**（退款36含继承28、旧Case9、行槽并发2），共享DTO1通过，reactor51.744秒；进一步复核确认分支后同组47通过、56.243秒。补已有入口回执的一般性修正后定向 **3通过/51.938秒**（含同键并发与原回执恢复）；不把这些重复测试相加。契约/OpenAPI **111通过/15.77秒**，限定格式通过。Windows Maven命令曾因参数中竖线被cmd解释而两次未执行，拆为两个限定正则命令后通过。

真实隔离MySQL/Flyway/HTTP；Commerce显式stub，模拟约束故障不影响原库。覆盖旧版本/过期/金额变化、同键改body、响应丢失后会话更新仍恢复原回执、双并发只一Case/绑定、旧入口已有单、UNKNOWN客户投影及无助手调用。原业务服务未启动、无Provider调用。R3代码在工作区独立验证，尚未作为本步提交。

## R3 聊天卡片和客户进度

独立SupportRefundCard/support-refund客户端挂到买家当前会话，商家不读取私有草稿；可准备/编辑保存/暂不申请/确认，持久未知请求按账号+会话隔离，同键原body恢复，刷新/切商品保留当前申请；客户进度独立5秒读取并可进入原详情补证。RECONCILING明确结果待确认，只有CLOSED_SUCCESS显示完成。

全前端 **34文件239通过/14.23秒**，typecheck/build通过（Vite1.14秒；视觉CSS收紧后629ms）。新增红测缺模块失败；首实现3失败是fixture会话版本与草稿不一致，修为显式同版本/未来到期；构建发现findLast超出原ES2022和fixture字面量类型，改reverse().find/准确类型，不升级依赖。后1测试structuredClone不能克隆Vue代理，改JSON序列化捕获实际请求；最终全通过，原断言保留。

`NODE_PATH=<bundled node_modules> <bundled node> scripts/check_chat_refund_closure.cjs`使用实际built Vue、Edge及真实loopback HTTP合成业务，**8项检查、浏览器错误0**，三桌面宽度无横溢、编辑/取消不建单、提交后回执不明503、刷新后相同key/body恢复一笔合成Case、UNKNOWN区分通过。[浏览器检查](browser/checks.json)、[确认卡片](browser/confirm.png)、[同一申请进度](browser/progress.png)、[结果待确认](browser/unknown.png)。视觉复核收紧卡片内边距选择器，避免全局消息样式覆盖，重建后同脚本再通过。脚本最初订单stub路径误写导致超时；第二次socket断开被浏览器传输层自动恢复，不适合作为手动重试断言，改为建单后明确503的回执不明场景再通过；没有改业务逻辑回避失败。

本步无真实Java/Web业务库联调、Provider或真实退款执行，不当Agent质量/延迟指标。下一小步同步Agent办理指南和受控申请摘要展示，避免仍引导用户离开会话重复填写。

## R4a 办理指南同步

追加support-guide-v3（2026.10.23-v3），保留旧v2字节；受控指南/固定步骤/阶段提示现在说明当前会话申请退款→编辑核对→确认、会话进度和我的售后补证。当前售后咨询允许合法退款入口，人工核查仍不建退款单，错误的“我的售后点击请商家核查”仍拒绝。manifest绑定新资源，不静默升级旧run。

指南/导航红测4失败，初实现仍4失败：指南过长使原Mock请求预算溢出、两项旧路由断言及一项冻结v2来源被当前v3拒绝。精简新段落、不扩大预算；将合法新入口移入正例，当前证据门禁仍验证旧v2拒绝。历史诊断测试显式绑定其原v2规则/原v2来源，只验证原诊断，不作为新v3表现；旧raw/脚本/来源未修改。首次扩收集因根PYTHONPATH缺失报错，补后326过1旧诊断失败，修正测试分代后客服单元 **327通过/7.38秒**，相关Ruff、4源码strict mypy通过。准备脚本曾语法错误未编辑，随后真实红测确认；均不计成功。

本步仅办理指引，摘要字段接线下一小步；真实Provider0，原项目停。
