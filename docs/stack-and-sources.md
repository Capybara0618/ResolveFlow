# 技术版本线与依据

v1.3说明（2026-09-25）：仅Agent框架获准迁移AgentScope 2.x Python SDK，见[迁移规格](agentscope-migration.md)。当前生产锁仍包含LangGraph，AgentScope尚未实测/锁定；AS01独立验证，AS02再更新生产锁。其他组件复用T00–T02实测记录，实际补丁/digest以infra/versions.lock.yaml、构建锁文件和docs/compatibility-report.md为准。Nacos/Sentinel/完整观测及reranker仍非核心，不因列在表中就必须部署。

## 1. 选型

| 组件 | 基线 | 锁定规则 |
| --- | --- | --- |
| Java | 21 LTS | 固定发行版与镜像digest |
| Spring Boot | 4.0.x | 匹配Cloud2025.1支持补丁，选已发布维护补丁 |
| Spring Cloud | 2025.1.x | BOM管理，禁止混2025.0 |
| Spring Cloud Alibaba | 2025.1.0.0 | 沿用已测BOM；Nacos/Sentinel可选，RocketMQ使用T00已测classic客户端，不假设存在对应starter |
| Gateway/Security/OpenFeign | 上述BOM对应 | 沿用T00已测spring-cloud-starter-gateway-server-webflux及序列化组合，不重新猜坐标 |
| Maven/MyBatis/Flyway | Maven3.9.x；MyBatis Boot4兼容线；Flyway BOM可用版 | T00真实最小事务与迁移验证，禁止SNAPSHOT |
| MySQL | 8.4 LTS | 固定patch与digest |
| Redis | 7.x | 固定patch，测试Lua限流 |
| RocketMQ | 5.x，Java官方兼容客户端 | NameServer+Broker；选与客户端匹配的调用模式，不混4.x/5.x样例 |
| Nacos | 3.1.x | 客户端由SCA BOM管理，服务端兼容实测 |
| Python | 3.12 | uv+uv.lock |
| AgentScope（目标，未实施） | 2.x Python SDK；2.0.8为已发布候选 | AS01验证依赖/循环拦截/PG恢复/strict后，AS02锁精确正式版；禁用dev/main与1.x混用 |
| LangGraph（历史兼容基线） | 当前锁1.2.11及PG checkpointer3.1.2 | T00历史spike保留独立环境与证据；AS02移除生产直接依赖，不删除旧测试 |
| FastAPI/Pydantic/MCP | FastAPI稳定版、Pydantic2、官方MCP Python SDK稳定版 | T00依赖解析与stdio工具调用测试 |
| PostgreSQL/pgvector | PG16、兼容稳定pgvector扩展 | 固定镜像，测试向量维度与过滤 |
| 检索 | jieba、rank-bm25、sentence-transformers | lock+embedding/reranker模型revision |
| 前端 | Vue3、TypeScript、Vite、Node22、pnpm | 不引入第二套前端框架，pnpm-lock.yaml |
| 观测 | OTel Collector、Prometheus、Grafana、Tempo | 官方稳定镜像digest，T00/T26验证OTLP链路 |

若MyBatis Boot4 starter确有兼容阻塞，先核实官方版本与最小复现；可用Spring JDBC实现相同Repository接口，记录ADR修订，不能偷偷改整个Boot版本。若涉及多个核心依赖不兼容，提交备选组合和成本，由用户决定主要版本回退。常规补丁锁定无需再询问。

## 2. T00兼容性关卡

本节为已执行的历史关卡要求。实际通过/未运行内容以任务归档与兼容报告为准，v1.2不把可选组件重新作为核心启动门槛。

必须验证：Maven解析+Java启动；Nacos config/import+服务发现；Gateway路由；MySQL事务/Flyway；RocketMQ发送消费；Sentinel基本熔断；Python依赖解析+PG checkpoint保存恢复；MCP stdio工具调用；跨Java/Python JSON/hash fixture；前端最小build。

临时技术验证可先在spikes/compatibility内进行，完成后只保留必要fixture与版本报告，生产工程按T01建立。不能通过禁用compatibility verifier、跳过测试或选择未发布版本过关。

## 3. 官方依据与应用边界

- [AgentScope已发布v2.0.8](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.8)：2026-09-25查到的迁移候选，不是本项目兼容结论；以release源码和AS01真实命令确认API/依赖。
- [AgentScope SDK与Service](https://github.com/agentscope-ai/agentscope)：只采用SDK，不引入平台部署。新站latest可能指向dev，不能依据开发版能力承诺稳定版本行为；公开扩展点能否覆盖所有调用及事务恢复必须实测。

- [Spring Cloud项目兼容矩阵](https://spring.io/projects/spring-cloud/)：Cloud2025.1对应Boot4.0，2025.0对应3.5；本次采用前者。版本支持状态以实施日核实为准。
- [Spring Cloud Alibaba 2025.1.0.0发布](https://github.com/alibaba/spring-cloud-alibaba/releases/tag/2025.1.0.0)：正式支持Boot4/Cloud2025.1，Nacos使用spring.config.import，RocketMQ与Sentinel有兼容更新。发布基线不等于任意后续补丁已实测。
- [LangGraph持久化](https://docs.langchain.com/oss/python/langgraph/persistence)：仅为T00历史选型依据，不再是v1.3生产目标。
- [LangGraph中断](https://docs.langchain.com/oss/python/langgraph/interrupts)：仅为历史依据；新框架仍不承诺外部exactly-once，不能继承旧验证结果。
- [RocketMQ消费重试](https://rocketmq.apache.org/docs/featureBehavior/10consumerretrypolicy/)：用于重试与DLQ配置核对，不代替业务对账。
- [MCP安全说明](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)：权限必须在可信边界验证；本版选stdio受控适配层。
- [pgvector官方说明](https://github.com/pgvector/pgvector)：本项目默认精确检索，小语料按硬过滤候选评分。

模型API提供商在live评测前选择，不影响既定架构。供应商SDK参数只能按其官方文档实现；兼容接口必须有真实能力测试，不能假设所有模型支持同样结构化输出/seed/token统计。
