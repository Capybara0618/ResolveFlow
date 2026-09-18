# 技术版本线与依据

核对日期2026-09-15。下面冻结组件与版本线，具体补丁/镜像digest必须在T00完成实际构建后写入infra/versions.lock.yaml和锁文件。当前未执行构建，不宣称整套依赖兼容已验证。

## 1. 选型

| 组件 | 基线 | 锁定规则 |
| --- | --- | --- |
| Java | 21 LTS | 固定发行版与镜像digest |
| Spring Boot | 4.0.x | 匹配Cloud2025.1支持补丁，选已发布维护补丁 |
| Spring Cloud | 2025.1.x | BOM管理，禁止混2025.0 |
| Spring Cloud Alibaba | 2025.1.0.0 | 已发布正式版，验证Nacos/Sentinel/RocketMQ starter |
| Gateway/Security/OpenFeign | 上述BOM对应 | 不单独猜starter版本；测试Jackson3序列化 |
| Maven/MyBatis/Flyway | Maven3.9.x；MyBatis Boot4兼容线；Flyway BOM可用版 | T00真实最小事务与迁移验证，禁止SNAPSHOT |
| MySQL | 8.4 LTS | 固定patch与digest |
| Redis | 7.x | 固定patch，测试Lua限流 |
| RocketMQ | 5.x，Java官方兼容客户端 | NameServer+Broker；选与客户端匹配的调用模式，不混4.x/5.x样例 |
| Nacos | 3.1.x | 客户端由SCA BOM管理，服务端兼容实测 |
| Python | 3.12 | uv+uv.lock |
| LangGraph | 1.x | StateGraph，官方PG checkpointer匹配版本锁定 |
| FastAPI/Pydantic/MCP | FastAPI稳定版、Pydantic2、官方MCP Python SDK稳定版 | T00依赖解析与stdio工具调用测试 |
| PostgreSQL/pgvector | PG16、兼容稳定pgvector扩展 | 固定镜像，测试向量维度与过滤 |
| 检索 | jieba、rank-bm25、sentence-transformers | lock+embedding/reranker模型revision |
| 前端 | Vue3、TypeScript、Vite、Node22、pnpm | 不引入第二套前端框架，pnpm-lock.yaml |
| 观测 | OTel Collector、Prometheus、Grafana、Tempo | 官方稳定镜像digest，T00/T26验证OTLP链路 |

若MyBatis Boot4 starter确有兼容阻塞，先核实官方版本与最小复现；可用Spring JDBC实现相同Repository接口，记录ADR修订，不能偷偷改整个Boot版本。若涉及多个核心依赖不兼容，提交备选组合和成本，由用户决定主要版本回退。常规补丁锁定无需再询问。

## 2. T00兼容性关卡

必须验证：Maven解析+Java启动；Nacos config/import+服务发现；Gateway路由；MySQL事务/Flyway；RocketMQ发送消费；Sentinel基本熔断；Python依赖解析+PG checkpoint保存恢复；MCP stdio工具调用；跨Java/Python JSON/hash fixture；前端最小build。

临时技术验证可先在spikes/compatibility内进行，完成后只保留必要fixture与版本报告，生产工程按T01建立。不能通过禁用compatibility verifier、跳过测试或选择未发布版本过关。

## 3. 官方依据与应用边界

- [Spring Cloud项目兼容矩阵](https://spring.io/projects/spring-cloud/)：Cloud2025.1对应Boot4.0，2025.0对应3.5；本次采用前者。版本支持状态以实施日核实为准。
- [Spring Cloud Alibaba 2025.1.0.0发布](https://github.com/alibaba/spring-cloud-alibaba/releases/tag/2025.1.0.0)：正式支持Boot4/Cloud2025.1，Nacos使用spring.config.import，RocketMQ与Sentinel有兼容更新。发布基线不等于任意后续补丁已实测。
- [LangGraph持久化](https://docs.langchain.com/oss/python/langgraph/persistence)：检查点支撑恢复；本项目额外实现任务领取与回调幂等。
- [LangGraph中断](https://docs.langchain.com/oss/python/langgraph/interrupts)：恢复会涉及节点重入，副作用需要幂等；本项目不靠框架承诺外部exactly-once。
- [RocketMQ消费重试](https://rocketmq.apache.org/docs/featureBehavior/10consumerretrypolicy/)：用于重试与DLQ配置核对，不代替业务对账。
- [MCP安全说明](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)：权限必须在可信边界验证；本版选stdio受控适配层。
- [pgvector官方说明](https://github.com/pgvector/pgvector)：本项目默认精确检索，小语料按硬过滤候选评分。

模型API提供商在live评测前选择，不影响既定架构。供应商SDK参数只能按其官方文档实现；兼容接口必须有真实能力测试，不能假设所有模型支持同样结构化输出/seed/token统计。
