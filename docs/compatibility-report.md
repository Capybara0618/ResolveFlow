# T00 依赖兼容与版本锁 · 实测报告

日期：2026-09-15。执行环境：Windows 11、Docker Desktop 29.3.0。
本报告只记录**本机实际运行过**的命令与结果。未运行的项在 §6 明确列出。

锁定结果写入 [infra/versions.lock.yaml](../infra/versions.lock.yaml)。
原始日志在 [reports/t00-compatibility/](../reports/t00-compatibility/)。
试验代码在 [spikes/compatibility/](../spikes/compatibility/)。

## 1. 结论

T00 两个工作包的验收项全部实测通过，G0 的两条硬性要求（无 SNAPSHOT、无跳过兼容检查）由 Maven Enforcer 规则机器校验。

| 测试套件 | 结果 |
| --- | --- |
| Java 集成测试 | **20 / 20 通过**，BUILD SUCCESS |
| Python 测试 | **18 / 18 通过** |
| 前端构建 | `vue-tsc --noEmit` + `vite build` 通过，产出 dist |
| Enforcer 兼容守卫 | 4 条规则全部 passed |

合计 38 个测试，全部在真实 MySQL 8.4 / PostgreSQL 16+pgvector / RocketMQ 5.3.3 / Nacos 3.1.0 容器上运行，无 mock 替代。

## 2. 环境基线与缺口

工作区此前只有文档，没有任何可运行代码。以下环境缺口会让 `docs/engineering.md` 里的命令直接失败，已全部补齐：

| 项 | 文档要求 | 本机初始状态 | 处理 |
| --- | --- | --- | --- |
| Java | 21 LTS | **仅 17** | 安装 Temurin 21.0.12.1+1，SHA-256 与 Adoptium 公布值逐位一致 |
| Maven | 3.9.x | **未安装** | 安装 3.9.16 |
| Python | 3.12 | 3.10.9 | uv 安装 3.12.13 |
| Node | 22 | 24.14.1 | 安装 22.23.2 |
| pnpm | 需要 | 未安装 | 安装 12.4.1 |
| Docker | 需起中间件 | 守护进程未运行 | 启动；Docker Hub 不可达，见 §5.6 |

注意：**本机默认 `java` 仍是 17**。构建必须显式设置 `JAVA_HOME=/c/Users/hjn/.jdks/jdk-21.0.12.1+1`。T01 的 doctor 入口必须在缺 Java 21 时明确失败，而不是回退到 17。

## 3. 验证矩阵

`spikes/compatibility/` 为临时验证工程，按 `docs/stack-and-sources.md` §2 的关卡逐项实测。

| 关卡 | 实际命令 | 结果 | 证据 |
| --- | --- | --- | --- |
| Maven 解析 | `mvn -B -ntp dependency:resolve` | 通过 | BUILD SUCCESS，无冲突 |
| Java 启动 | `java -jar spike-service-...jar --spring.profiles.active=nacos` | 通过 | 12.3s 启动成功 |
| Nacos config/import | 发布 `spike-service.yaml` 后 `GET /spike/config` | 通过 | 返回 `fromNacosDefault:false`，值确实来自 Nacos |
| Nacos 服务发现 | `GET /spike/discovery` | 通过 | 服务列表含 `spike-service` |
| Gateway 路由 | `curl localhost:8080/spike/ping` | 通过 | 经 `lb://spike-service` 返回后端响应 |
| OpenFeign + LB | `GET /spike/via-feign` | 通过 | 按服务名解析并调用成功 |
| MySQL 事务/Flyway | `mvn test -Dtest=MySQLTransactionIT` | 通过 9/9 | 真实 MySQL 8.4，迁移 V1 应用成功 |
| RocketMQ 收发 | `mvn test -Dtest=RocketMqIT` | 通过 2/2 | 真实 broker，含 UTF-8 中文载荷往返 |
| Sentinel 熔断 | `mvn test -Dtest=SentinelIT` | 通过 3/3 | 流控与降级规则都真实触发 |
| 跨语言 hash | `mvn test -Dtest=CrossLanguageHashIT` | 通过 6/6 | Java 独立复现 Python 全部 hash |
| Python 依赖解析 | `uv lock` / `uv sync --frozen` | 通过 | 71 包解析，冻结安装成功 |
| PG checkpointer | `pytest tests/test_checkpointer.py` | 通过 5/5 | 真实 PG16，跨连接恢复状态 |
| MCP stdio | `pytest tests/test_mcp_stdio.py` | 通过 3/3 | 真实 stdio 会话，list/call 工具 |
| 前端最小构建 | `pnpm build` | 通过 | vue-tsc 类型检查 + vite 产物 |

### 3.1 事务测试覆盖的不变量

`MySQLTransactionIT` 断言的是 `docs/domain-model.md` 的不变量本身，不是实现的复述：

- **INV-01**：`refunded + reserved <= paid`。应用层条件 UPDATE 与数据库 CHECK 双层验证；并发 16 线程抢同一订单行时，只有 1 个成功，失败者没有把预留泄漏进账本。
- **INV-02**：同一订单行只能被一个 operation 占用，退款/补发互斥。失败方不会覆盖持有方。
- 版本 CAS：过期 version 的 UPDATE 影响 0 行。
- 完整生命周期 reserve→start→commit：预留转已退恰好一次，重复 commit 被拒。
- 直接绕过应用层写 SQL 时，CHECK 约束仍然拦截。

## 4. 锁定版本

完整清单见 [infra/versions.lock.yaml](../infra/versions.lock.yaml)。核心组合：

| 组件 | 锁定版本 | 备注 |
| --- | --- | --- |
| Spring Boot | 4.0.8 | 4.0.x 最新补丁；Spring Framework 7.0.9 |
| Spring Cloud | 2025.1.3 | 2025.1.x 最新补丁（其父 POM 声明 Boot 4.0.8） |
| Spring Cloud Alibaba | 2025.1.0.0 | 该线唯一正式版 |
| Gateway | `spring-cloud-starter-gateway-server-webflux` 5.0.3 | 旧坐标已不存在，见 §5.2 |
| Nacos client / server | 3.1.1 / v3.1.0 | 客户端由 SCA BOM 管理 |
| Sentinel | 1.8.9 | |
| MyBatis starter | **4.1.0** | 必须显式压过 SCA 管理值，见 §5.3 |
| Flyway | 11.14.1 | Boot 管理版本；另需 `spring-boot-flyway`，见 §5.1 |
| mysql-connector-j | 9.7.0 | |
| RocketMQ client | **5.3.1**（classic） | 见 §5.4 |
| Jackson | 3.1.5 与 2.21.5 共存 | Boot 用 3，Flyway 带 2 |
| Testcontainers | **2.0.5** | 1.x 在本 Docker 版本不可用，见 §5.5 |
| LangGraph / checkpointer | 1.2.11 / 3.1.2 | checkpoint 4.2.0 |
| MCP Python SDK | 2.2.0 | 见 §5.7 |
| 镜像 | mysql 8.4、pgvector pg16、redis 7.4、rocketmq 5.3.3、nacos 3.1.0 | 全部按 digest 固定 |

## 5. 实施前必须知道的兼容性发现

以下每一条都是实测中真实踩到并解决的，不是从文档推断的。按影响排序。

### 5.1 Boot 4 拆分了自动配置模块，Flyway 会静默不执行

`spring-boot-autoconfigure:4.0.8` 里 Flyway 相关类数量为 **0**（实测 `unzip -l | grep -ci flyway`）。只声明 `flyway-core` 时，应用照常启动、**不报任何错**，但迁移根本不跑——表不存在，直到第一条 SQL 才暴露。

必须同时声明 `org.springframework.boot:spring-boot-flyway`。这一条对后续每个用 Flyway 的服务都适用。

### 5.2 Gateway starter 改名

`spring-cloud-starter-gateway` 在 5.x **不存在**（Maven Central 无元数据）。Cloud 2025.1 的正确坐标是 `spring-cloud-starter-gateway-server-webflux`。`docs/stack-and-sources.md:13` 只写"上述 BOM 对应"，未点名，直接照抄旧样例会失败。

### 5.3 SCA BOM 会拉低 MyBatis，需要显式压过并加守卫

`spring-cloud-alibaba-dependencies:2025.1.0.0` 的 `dependencyManagement` 里**确实**管理了 `mybatis-spring-boot-starter`（`${mybatis.version}`，3.0.x 线，只兼容 Boot 3）。本工程要求 Boot 4 兼容线，实测解析结果为 **4.1.0**，SCA 的值没有生效。

这个结果依赖 Maven 的版本仲裁细节，属于"今天对、改一行 pom 就可能悄悄变错"的类型，所以已在父 POM 加 Enforcer 规则：`mybatis-spring-boot-starter` 与 `mybatis-spring` 一旦低于 4.0 直接构建失败。

### 5.4 RocketMQ 只有 Stream binder，没有 starter（文档冲突）

见 §6.1。已按用户确认采用官方 classic 客户端直连。

### 5.5 Testcontainers 1.x 在 Docker Engine 29 上无法连接

Docker 29 的 `MinAPIVersion` 是 **1.40**，而 Testcontainers 1.21.4 依赖的 docker-java 3.4.2 协商旧 API，得到的响应是 HTTP 400 加一个空 Info 体，报错信息是容易误导的 "Could not find a valid Docker environment"。

必须用 Testcontainers **2.0.5**（docker-java 3.7.1）。同时 2.x 重命名了模块：`org.testcontainers:mysql` → `testcontainers-mysql`，`junit-jupiter` → `testcontainers-junit-jupiter`。

另外两点：Windows 下需设 `DOCKER_HOST=npipe:////./pipe/dockerDesktopLinuxEngine`；**不要**设 `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`，设了会让 ryuk 挂载失败。ryuk 镜像版本必须与 Testcontainers 版本匹配（2.0.5 → ryuk 0.14.0）。

### 5.6 Docker Hub 在本网络不可达

`registry-1.docker.io` 的 DNS 被污染（解析到无关 IP），直连超时。已通过 `docker.m.daocloud.io` 镜像源拉取，然后打回规范标签。

安全性说明：所有镜像都按 **digest** 固定，且实测镜像源返回的 digest 与规范仓库名下的 digest **完全相同**（内容寻址），因此镜像源无法在 digest 校验下替换内容。这是本地开发环境的绕行方案，不是可移植的 CI 方案——CI 需要自备可达的镜像源或预置镜像。

### 5.7 MCP Python SDK 2.x 重命名了 FastMCP

`mcp.server.fastmcp` 在 2.x **不存在**；已改为 `mcp.server.mcpserver.MCPServer`（`@server.tool`、`server.run("stdio")` 用法相近）。另外 `CallToolResult` 的字段是 `is_error` / `structured_content`（snake_case）。

任何 1.x 时代的 MCP 示例代码在 T18 都不能直接用。

### 5.8 Nacos 3.x 的两处行为变化

- **必须设置 `NACOS_AUTH_TOKEN`**（Base64，解码后 ≥32 字节），即使 `NACOS_AUTH_ENABLE=false`。否则容器以 255 退出。
- **v1/v2 配置 API 已废弃**：`GET /nacos/v2/cs/config` 返回 `410 Gone`，并提示改用 `/v3/admin/cs/config`；而 v3 admin API 需要登录态（403）。v1 路径目前仍可用但同样标记废弃。T19 的政策 bundle 同步要走客户端 gRPC（已实测可用），不要依赖这些 REST 管理接口。

### 5.9 MySQL CHECK 约束违规的异常类型

CHECK 违规返回 SQLState `HY000` / error `3819`，Spring 翻译为 `UncategorizedSQLException`，**不是** `DataIntegrityViolationException`。资金相关的约束兜底错误处理不能只 catch 后者。

### 5.10 LangGraph checkpointer 的确切 API

导入路径是 `langgraph.checkpoint.postgres`（发行名 `langgraph-checkpoint-postgres`，两者不同）。`PostgresSaver.from_conn_string(...)` 是上下文管理器，首次使用前必须 `.setup()`。已实测：跨新连接可恢复状态（这是 T22 恢复能力的前提）、thread 之间隔离、checkpoint 历史追加而非覆盖。

### 5.11 RocketMQ broker 必须设 brokerIP1

不设 `brokerIP1` 时 broker 广播容器内网 IP，宿主上的 Java 客户端连不上。spike 里固定为 `127.0.0.1`。

## 6. 文档冲突与处理

按 AGENTS.md 要求，实质冲突逐条列出位置、影响与处理，不自行绕开。

### 6.1 RocketMQ：starter 与官方客户端指向两条路径

- `docs/stack-and-sources.md:12`：要求"验证 Nacos/Sentinel/**RocketMQ starter**"，字面指向 `spring-cloud-starter-alibaba-rocketmq`。
- `docs/stack-and-sources.md:17`：又写"RocketMQ 5.x，**Java 官方兼容客户端**"。

**实测事实**：前一个坐标**在任何已发布版本中都不存在**。SCA 2025.1.0.0 的 BOM 里只有 `spring-cloud-starter-stream-rocketmq`（Spring Cloud Stream 绑定层）和 `spring-cloud-starter-bus-rocketmq`，以及裸的 `rocketmq-client` / `rocketmq-acl`。

**影响**：走 Stream binder 会引入一层绑定框架，与 `docs/architecture.md` 的本地 Outbox + 显式消费控制（inbox 去重、毒消息、DLQ、重驱动）张力较大。

**处理**：**已请你确认**，采用 `org.apache.rocketmq:rocketmq-client` 5.3.1（SCA BOM 管理版）直连，不引入 Stream。已实测收发成功。另一条路径 `rocketmq-client-java`（gRPC）需要额外部署 gRPC proxy，与"NameServer+Broker 两容器"的既定形态不符，未采用。

**建议**：修订 `docs/stack-and-sources.md:12`，把"RocketMQ starter"改为"RocketMQ classic 客户端"，避免后续实施者再撞一次。

### 6.2 Gateway 坐标未点名

`docs/stack-and-sources.md:13` 写"Gateway/Security/OpenFeign | 上述 BOM 对应 | 不单独猜 starter 版本"。方向正确，但 Cloud 2025.1 已把 starter 改名（§5.2），建议在文档中补上确切坐标。

### 6.3 Node 22 与文档未提及的版本线漂移

`docs/stack-and-sources.md:24` 固定 Node22。本机原有 Node 24，已按要求另装 22.23.2 并关闭该偏差。Vite 8 / TypeScript 5.9 均已实测可用；TypeScript 最新线已是 7.x（Go 重写版），本工程暂留在 5.9.3，理由见 §7。

## 7. 未验证项

以下项目**没有运行**，不得视为通过：

| 项 | 原因 |
| --- | --- |
| Redis Lua 限流 | 容器已起来且健康，但限流逻辑属 T27，T00 关卡未要求行为验证 |
| OTLP 观测链路 | 观测 profile 属 T26 |
| live 模型调用与效果 | 未配置模型 API 与预算；按 AGENTS.md 不得假定已授权消费 |
| embedding / reranker 模型 revision | 属 T19，届时需固定 revision |
| pgvector 维度与硬过滤 | 已实测扩展可用与精确检索排序，但真实维度与过滤属 T19 |
| Nacos 客户端 3.1.1 与服务端 3.1.0 的官方兼容矩阵 | **未找到官方书面兼容声明**；本次只是实测可用（注册、发现、配置导入均通过），结论限于实测范围 |
| TypeScript 7 / Vite 8 的新特性 | 未使用；构建在 5.9.3 + vite 8.3.0 上通过 |
| 故障注入、性能、RAG 对照 | 属 T29/T30 |
| CI 流水线 | 属 T01/T32 |

另需说明：`spikes/` 是临时验证工程，**不是**生产代码。T01 会按 `docs/engineering.md` 的目录重建 `java/`、`agent/`、`web/`，spike 只保留 fixtures 与版本报告（spike 代码目前仍在工作区，待 T01 建立正式骨架后按需清理，不擅自删除）。

## 8. 复现步骤

```bash
# 0) 环境（本机路径，CI 需另配）
export JAVA_HOME=/c/Users/hjn/.jdks/jdk-21.0.12.1+1
MVN=/c/Users/hjn/.maven/apache-maven-3.9.16/bin/mvn
export DOCKER_HOST="npipe:////./pipe/dockerDesktopLinuxEngine"

# 1) 起基础设施
docker compose -f spikes/compatibility/infra/spike-compose.yaml up -d

# 2) Java 全部关卡（含 Enforcer）
cd spikes/compatibility/java-spike && $MVN -B -ntp validate && $MVN -B -ntp test

# 3) Python 全部关卡
cd spikes/compatibility/python-spike && uv sync --frozen && uv run --frozen pytest tests/ -v

# 4) 前端构建
cd spikes/compatibility/web-spike && pnpm install --frozen-lockfile && pnpm build
```

跨语言 fixture 的两个输入文件在 `spikes/compatibility/contracts/`：Java 与 Python 各自实现 RFC 8785 规范化，两边都必须复现冻结在 `cross-language-hash-expected.json` 里的值。

## 9. 下一阶段建议

T00 已满足进入 T01 的条件。建议顺序与要点：

1. **T01 立即处理环境可移植性**：doctor 入口必须检查 Java 21（不能回退 17）、Docker 可达性、`DOCKER_HOST` 与镜像源。本报告 §2 的六个缺口都应在 doctor 里有明确报错。
2. **T01 建立正式骨架时直接带上已验证的守卫**：把 Enforcer 规则、`spring-boot-flyway` 这类"不写就静默失效"的依赖、以及 §5 的启动参数写进模板，避免每个服务重复踩。
3. **T02 契约固化前先确认 §6.1 的文档修订**：`stack-and-sources.md:12` 的表述若不改，后续实施者仍会去找不存在的 starter。
4. **T02 的跨语言 fixture 已有可用起点**：`spikes/compatibility/contracts/` 的两个文件和两侧实现可直接升级为正式契约测试，不必从零设计。
5. **RocketMQ 版本选择留一个待决项**：SCA 管理的是 5.3.1，社区最新是 5.5.1。本次以 BOM 一致性优先选了 5.3.1 并实测通过；若后续需要 5.5.x 特性，需要重新验证与 broker 5.3.3 的匹配性。
6. **Nacos 兼容矩阵缺口**：§7 提到的官方兼容声明缺失，建议在 T03/T19 前用更长周期的稳定性观察补上，而不是仅凭一次启动成功。

T00 未修改任何业务设计、服务边界或不变量；`docs/` 下除本报告外未改动，`tasks/todo.md` 只更新了 T00 的记录条目。