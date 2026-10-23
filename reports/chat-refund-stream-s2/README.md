# S2：咨询事件与页面进度

2026-10-23，沿[开发方案](../../docs/customer-chat-refund-stream-v1.md)实施。事件不推进会话输入版本，不增加模型调用。

## S2a：事务事件账本

- 追加V29迁移，增加独立event_sequence及会话事件表。接收、领取、失效、失败/待重试及正式回答发布记录到同一个原业务事务；最终事件引用同一已持久message_id/文本/来源。旧fence不能写终局事件，不修改原模型循环。
- 每会话保留最近512条事件，写入时清理该会话超过24小时的事件；未活跃会话物理清理为惰性。旧游标恢复快照由S2b接入，尚未提供对外SSE或Python工具进度。
- 关键三测试先3 errors（表不存在）；实施后完整SupportApiTest 22通过，0失败/跳过，真实临时MySQL/Flyway迁移。验证发送与接收事件一起回滚、连续新输入失效旧turn、独立事件序号、一次正式回复/事件、原本人/商家隔离及无退款副作用。

实际命令（cwd java，JAVA_HOME=`C:/Users/hjn/.jdks/jdk-21.0.12.1+1`）：

```powershell
./mvnw.cmd -B -pl case-service -am '-Dtest=SupportApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./mvnw.cmd -B -pl case-service '-DspotlessFiles=.*Support.*[.]java' spotless:apply spotless:check
```

测试22项33.89秒，reactor总50.370秒；限定Support文件格式检查通过。初次PowerShell未完整引用`-Dsurefire.failIfNoSpecifiedTests=false`导致生命周期参数错误，未运行测试，修正引用后执行红绿测试。格式文件参数先误用glob、再含管道被cmd拆分，两次失败均未改文件；改为不含shell元字符的正则后通过。

无真实Provider请求，usage仍2011；生产项目和原数据库未启动，测试仅使用Testcontainers临时库，未清理日常数据。网页订阅、工具进度、正文增量与聊天退款尚未交付。

## S2b：鉴权SSE与断线恢复

- 新增GET `/api/v1/support/conversations/{id}/events`，只有本人平台买家可订阅；无身份401，其他买家/商家404，在流开始前拒绝。每次读取重新检查身份/可见性；250ms读取一批有序事件、15秒注释心跳、10分钟连接期限，断开/关闭应用回收订阅。只读连接不派发Agent，两个共享线程，不为字符开线程。
- SSE使用独立十进制字符串id，Bearer/Last-Event-ID在header，no-store及X-Accel-Buffering no。首次、错误/过期/超出保留区间游标返回含当前正式会话的stream.snapshot；短共享锁内取得快照与游标，网络发送在事务外。当前尚无模型草稿，S3需扩展生成视图快照。
- HTTP红测1失败（原路由不存在返回404而非401）；实现后完整SupportApiTest 26通过，0失败/跳过，35.56秒（reactor50.486秒）。包括已连接HTTP客户端收到后续实际发布、不靠客户端轮询；按游标只读续接；513次追加后只留512条，旧/过期游标恢复且输入版本不变。
- OpenAPI新增已实现路由/封闭包络，增加共享fixture与契约校验；首轮1失败/104通过，发现OAS3.1不采用nullable，修为显式string/null后105通过（15.35秒）。原路由全部身份/写幂等断言保留，新增路由只读401/404单独验证。Support限定格式检查通过。

实际命令除S2a的Java完整测试/格式外：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_support.py agent/tests/unit/test_contracts_openapi.py -q
```

S2a提交`1f619a3`已普通push/远端核实。S2b仍未接页面、未声明工具查询/正文实时输出；无真实模型请求或生产库迁移，静态预期稿保留。

## S2c：页面订阅与阅读体验

- 抽取复用原fetch SSE读取器，保持Case读取入口；新增咨询包络类型/校验、逐帧推进游标、重连去重、Bearer/Last-Event-ID及可取消退避。半途断流不会丢失已交付游标；身份拒绝停止重连；取消时关闭reader，不重发任何用户消息。
- 买家只订阅当前会话，切商品/卸载取消旧订阅，商家不订阅私有流。当前run/input匹配才更新处理状态或同一正式回答；另一个输入超前时只读刷新。快照/刷新合并已加载历史，旧版本不覆盖新结果；并发刷新期间的新事件保留待刷新标记。
- 活跃断线2秒只读降级；健康的纯助手会话不再8秒等答案，商家/人工核查仍保留8秒读取，未伪称人工消息也有新流事件。向上阅读不强制滚动，出现“有新内容·回到最新”；RUNNING改为实际“处理问题”，尚未接工具事件时不声称正在查阅来源。
- 新客户端红测缺模块1suite失败；实现后新/原Case事件6通过，再页面/事件24通过和typecheck通过，最后完整前端31文件223项通过（12.25秒），vue-tsc+Vite构建通过（867ms）。测试为Vitest/jsdom与合成Response；真实SSE HTTP已由S2b验证，尚未运行浏览器+生产服务体验或模型首字计时。

实际命令：`pnpm --dir web test -- tests/support-workspace.spec.ts tests/support-events.spec.ts tests/events.spec.ts`、`pnpm --dir web typecheck`、`pnpm --dir web test`、`pnpm --dir web build`。

S2b提交`2e35c5b`已普通push/远端核实。下一项验证Gateway是否及时转发分块；Python实际工具进度、正文S3、聊天退款R1–R3仍未接线。真实Provider新调用0，原库/项目未启动。
