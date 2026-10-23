# 会话流与退款确认目标协议

2026-10-23，配套[开发方案](customer-chat-refund-stream-v1.md)，下列为拟新增协议，尚未实现；实施时同步`contracts/core`、Java/Python/TS类型与fixture。原根目录兼容契约不覆盖，数据库迁移只追加，序号按届时最新迁移确定。

## A. 真实流的边界

唯一SDK循环仍按一次模型调用得到一个完整ModelReply。支持流式的咨询ModelClient内部以HTTP流读取Provider响应，收到增量时调用旁路observer，结束时拼回原始完整决定并解析；同一次请求只计一笔调用/预算，不能为了可视化再调用第二个模型。原退款调查客户端默认行为保持，咨询的stream模式进入新manifest，旧run不静默升级。

理解/工具选择阶段的JSON、原始思维链、customer_claims和内部错误不展示。增量解析器只提取已明确kind=ANSWER_PARTS的parts[].text；若kind在末尾才出现，先有界缓冲直到确认，不从任意"text"字段猜正文。不改变模型必需输出的含义，也不要求SDK升级未锁API。

正文的UTF-8/JSON字符串跨chunk、引号/反斜杠、Unicode转义、半个占位符必须正确处理。只在占位符完整且字段对应当前已读同主体来源可确定取值时输出值；无法确定的占位符先缓冲，不能输出{{PAID_AMOUNT}}、猜金额或从商品展示补值。source和facts可能在text后面，相关片段允许延后到元数据可验证；普通说明可以先展示。用于金额/操作的最终卡片只在完整答案被原Harness接纳后出现。

正文增量是可重置的“生成视图”；正式assistant message仍由当前Java版本/fence核验后原子发布。终局失败/修复不能保留被拒草稿为历史或证据。实现优先保证draft→reset→commit语义正确，不能通过前端禁止补充用户消息来逃避旧turn问题。

## B. 客户事件流

拟新增`GET /api/v1/support/conversations/{id}/events`，Bearer身份与会话GET同主体检查，跨本人/商家隐藏404。每个页面仅订阅当前商品会话；商家不订阅买家的私有模型流，原核查消息和退款Case投影继续独立授权。

SSE格式`id:事件序号`、`event:类型`、`data:JSON`，UTF-8，以双换行终止，支持Last-Event-ID。事件序号独立于conversation.version；进度/delta本身不新增正式消息或推进输入版本，否则会把自身运行不断判过时。心跳注释不增加事件序号。

共同包络：`{event_id,conversation_id,run_id,input_version,attempt_id,kind,payload,created_at}`。Java使用已持久的当前turn检查主体/input/fence，前端再按当前会话、run及attempt丢弃过期/重复增量。attempt区分模型修复前后的正文，不能与退款operation混用。

| 事件 | payload与页面行为 |
| --- | --- |
| turn.accepted | run_id/排队状态；确认消息已保存，非模型开始 |
| activity.started/completed | 受控类别ORDER/SHIPMENT/POLICY/GUIDE；来自实际工具事件，不带内部参数/私有原文，不伪造思考进度 |
| answer.started | attempt_id；建立/切换本轮生成气泡 |
| answer.delta | part_id、递增offset、text增量；按序追加，原始JSON不进入DOM |
| answer.reset | 新attempt_id；丢弃上次未接纳生成视图，保持同一气泡 |
| answer.committed | Java正式message_id/sequence、完整最终文本与可见来源；替换草稿，一次持久化 |
| answer.failed/stale | 受控公开原因；清理生成视图，不自动新建run重付 |
| refund.draft_ready | 当前用户可读取的draft_id/revision；完整来源/资格确认后才启用按钮 |
| refund.created/progress | draft/case引用和客户可见状态；读取原Case投影，不泄露内部授权 |
| stream.snapshot | 当前生成视图/正式消息/当前卡片及last_event_id；游标失效或历史压缩时恢复，不重跑模型 |

事件保存有界：正文总量继续受原4000字符等限制，单turn最多512条对外事件，50–100ms或约40字符合批；达到上限先合并当前draft为snapshot而不是丢最终提交。只保留重连所需最近事件，旧游标返回snapshot；完整模型请求/响应仍由原PG调用账保存。初始设计保留最近24小时流事件，旧正式历史长期按原策略，不把事件表变成无限token日志。

后台→Case拟增`POST /internal/v1/support/turns/{run_id}/stream-events`，使用独立、限定本run的`support:progress`能力（不是扩大只读业务工具token）；请求含派发fence/input_version、事件批次key和序号。批次幂等，未知旧批不得覆盖新正文；网络发送在数据库事务外，短事务仅核验并追加事件。正式终局回复仍走已有返回/发布链路，answer.committed和正式message同本地事务，不由Python伪造持久message。

Provider `[DONE]`前usage尾帧单次结算；断流缺usage需标estimated/unknown，不能用0假装无成本。取消页面订阅只断UI连接，不取消已消费的退款动作；消息新版本使旧run停止发布。中途网络异常不自动重发Provider请求，原UNKNOWN策略保持。请求重连仅续读事件/快照，不能触发模型。

Gateway/Case须关闭流响应缓存与代理缓冲，及时flush。沿已有单有界worker和SSE订阅生命周期管理，浏览器关闭释放订阅；慢读端合并draft快照，不为每字符创建新线程。读取更早消息时保持阅读位置，流继续收但不强制滚动。

## C. 申请草稿与确认

拟新增：

| 路由 | 目标含义 |
| --- | --- |
| POST /api/v1/support/conversations/{id}/refund-drafts | `{expected_version,assistant_message_id?,reason?}` + 幂等键；由本人请求或本人已接纳退款建议生成草稿，Java取权威金额/资格；不会建Case |
| PATCH /api/v1/support/conversations/{id}/refund-drafts/{draft_id} | `{revision,reason}`；保存用户编辑稿、revision递增，不编辑金额/订单行/身份 |
| POST /api/v1/support/conversations/{id}/refund-drafts/{draft_id}/confirm | `{revision,expected_version}` + 原幂等键；重核资格、创建或返回已关联Case、原子关联及回执 |
| GET /api/v1/support/conversations/{id}/refund-application | 当前草稿/已关联case及客户专用进度投影；刷新恢复同一申请 |

以上是目标路径，最终命名随契约小步确认，不先在OpenAPI伪装已有实现。原因长度复用现有Case description约束；无摘要时允许手填，不让模型失败锁死申请入口。旧页面仍可复用原POST /cases。

建议追加`support_refund_draft`和`support_refund_application`（Case同库，独立迁移）。草稿含本人/会话/订单行、来源assistant_message_id、对应输入版本、reason、revision、权威金额快照及状态；关联表保存draft→case和建单幂等引用。草稿默认30分钟有效，提交前资格仍实时核对；过期显示重新核对，不能自动悄悄提交改后的金额。

草稿状态DRAFT/CONFIRMED/CANCELLED/EXPIRED，CONFIRMED绑定唯一case_id。一个草稿只确认一次；同会话/行遇已有活跃或成功申请直接展示既有申请，不按新幂等键再建同一退款。若历史已关闭且现有业务允许重新申请，须显式新draft，不复用旧已确认草稿。

创建与关联需复用CaseService内部业务及CaseWriter的同库事务扩展点：已有建单外部Commerce读取仍在事务外；本地写Case、原幂等回执、draft确认和会话关联同事务。不能在浏览器先createCase成功后单独写关联，或将外部网络包进长事务。前端未知结果保留同键/同body查询原回执；已建Case而HTTP断开重试恢复原单，不生成第二次申请。

金额来自当前订单行实付/现有申请资格核验，不能来自模型、商品展示价或请求参数；平台买家需沿现有本人订单到merchant/customer的绑定解析，不把买家账号直接当本店customer身份。只有用户明确确认的reason/材料进入申请，模型流式草稿不自动共享。Case状态和退款执行结果继续由原服务/事件投影决定，UNKNOWN不标失败或成功、不换ID重付。
