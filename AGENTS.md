# ResolveFlow 实施约定

## 当前目标

框架文档v1.3，保持v1.2个人项目范围和验收深度，不做公司级平台。AgentScope 2.0.8已接入唯一生产循环。当前进度只在tasks/todo.md顶部维护，当前执行说明为tasks/handoff-current.md；历史交接不能作为开工指令。任务账本优先于旧聊天。

## 开始工作

1. 读README.md、docs/core-scope.md、tasks/handoff-current.md、tasks/plan.md及tasks/todo.md顶部/当前任务；再按任务读专题规格，AS和旧交接只按需定位历史决定，不逐份全量加载。
2. 检查工作区现状与当前实际记录，再读当前任务相关规格/源码/测试；不加载整个旧聊天。
3. 按当前账本推进C08→C09→C10及后续核心任务；不重做C00/AS迁移，不按旧T03–T39推进。修复与接入完成不得自动勾H1–H5；非Agent框架依赖沿用原锁。
4. 已有客户端可能仍在执行旧计划，发现同文件并行编辑先确认交接，不能覆盖别人的改动。
5. Codex与DSH切换按tasks/handoff-current.md第5节：原执行者先收尾并明确停止写入，接手者先只读核验再接管。同一工作区只允许一个业务实施写入者；交接快照只更新tasks/todo.md顶部，不另建第二份进度。额度突然中断走紧急接管，不假定原执行者已停止或未提交工作已同步远端。

## 规范权威

范围以docs/core-scope.md为准，业务以product-spec、状态/不变量以domain-model、Agent以agent-harness及agent-spec/context-engineering/trajectory-replay为准；本次框架替换与技术门禁以docs/agentscope-migration.md为准。AgentScope只负责主循环，领域Harness仍负责硬约束；运行快照/fence须重新实测，不能继承T00的LangGraph通过结论。

docs/core-contracts.md是当前目标协议；docs/contracts.md与现有根目录Schema/OpenAPI是T02旧兼容基线。C00创建contracts/core、对应类型/fixture与核心路由覆盖，旧测试保留。不把旧Schema允许的RESHIP当核心可执行权限，也不删除断言来通过迁移。

tasks/todo.md中的AS00–AS02为框架迁移插入段，C00–C13仍为核心交付计划；tasks/archive与旧交接/审阅记录仅为历史，旧T35–T39“全部必做”已撤销。规范冲突应指出并解决，不任选方便版本。

## 固定范围与不变量

- 核心为Gateway、Case、Commerce三个Java进程与Python Agent；不默认部署Fulfillment或完整观测集群。
- 只执行单订单行全量模拟退款；不开发补发、库存、跨动作权益Saga或执行中取消。
- 同行最多一次成功退款；订单已退+预留不超过支付额；UNKNOWN不释放、不换ID重付。
- 授权消费前可撤销/更新并使旧revision失效；消费后禁止修改输入和取消。
- Agent无退款、审批、政策修改或跨主体读取权限；模型confidence不是授权。
- Outbox按至少一次；inbox、业务结果和本地事件同事务；外部网络调用不放长事务。
- Java拥有工单/授权/金额，Python拥有run；checkpoint与回调受fence保护。
- 已持久模型结果可复用；未落库响应可能重复计费，不承诺零重复调用。
- 模型按Observation选行动，Harness控制权限/预算/终止，不预设完整工具路径。
- 上下文保留关键事实、来源/版本/冲突，原文与模型推断分开；实际请求可追溯。
- 同run恢复不静默换manifest或重置预算/deadline；strict回放不访问网络/业务写入口，缺记录明确失败。
- 指标必须真实，mock/live/合成数据分开，不宣称商用用户或生产高可用。

## 实施方式

- 按纵向小步，单次通常3–5核心文件；大工作包先拆子步，先关键失败测试再实现。
- 复用Java21/Spring/MyBatis与Python/FastAPI/MCP/PG现有锁；仅Agent框架获准迁移AgentScope 2.x，先隔离spike再锁正式发布版本，不混1.x/dev API，不全栈重选。
- 唯一生产Agent循环由AgentScope驱动；不将原HarnessRunner完整循环套进SDK。预算/权限拦截覆盖所有模型/工具调用，SDK会话保存不等于受fence保护的恢复。
- 风格/命令见docs/engineering.md；已有verify入口可用，但未来suite/profile未实现不可零步骤报成功。
- 契约、类型、fixture、生产者/消费者同步；迁移只追加，不改已执行迁移。
- 每完成项记录日期、文件、实际命令、测试/报告、失败与未运行；不得只勾任务。
- 保留代码、测试、数据库和用户改动；不清库、删卷或重写历史。用户已于2026-09-26授权：每个验证通过的独立小步（含修复/文档）立即commit并正常push到本仓库已确认的远程跟踪分支，无需逐次询问；不等整包完成。流程与失败处置见docs/engineering.md第8节。
- 提交仅包含本步及已核实必要依赖的改动、测试和记录；不盲用git add .或夹带他人暂存内容，不提交密钥/数据库快照/原始敏感日志。推送失败保留本地commit并明确报告，禁止force push、自动重写历史或悄悄跳过推送继续堆积功能。
- 不提交密钥，不开未经确认的收费评测、购买资源或公网部署。
- 范围内普通实现自行处理；不默认加多Agent、通用插件平台、反事实world回放、额外MQ或微服务。

## 完成标准

按核心任务及evaluation验收即可完成，不因延期功能阻塞。各阶段报告可演示行为、通过/失败/未运行和下一步。审查重点C05退款、C09恢复、C12实验、C13主张；简历证据以真实实现决定，不以组件数量凑亮点。
