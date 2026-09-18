# 工程规范与运行约定

## 1. 目标目录

```
java/
  pom.xml, mvnw, mvnw.cmd, .mvn/
  shared-kernel/
  gateway/
  commerce-service/
  fulfillment-service/
  case-service/
agent/
  pyproject.toml, uv.lock
  src/resolveflow/{api,runtime,harness,tools,policies,callbacks}/
  # runtime: worker/checkpointer；harness: runner/context/actions/budget/session/verifier
  tests/{unit,integration}/
web/                      # Vue3 + TypeScript + Vite
contracts/                # JSON Schema、后续OpenAPI和跨语言fixtures
infra/                    # compose.yaml、镜像锁、监控配置
fixtures/{business,policies,provider}/
evals/{datasets,baselines,runner,metrics,replay,variants}/
tests/{system,faults,performance}/
scripts/                  # verify.ps1与Linux等价入口
reports/                  # 不含敏感信息的实验结果
docs/
tasks/
```

## 2. 命令约定

这些是T01以后必须实现的命令契约，目前尚不存在。工作目录均为仓库根；先提供PowerShell入口，CI使用Linux等价脚本。脚本不得内部跳过失败测试后返回0。

| 用途 | 预期命令 |
| --- | --- |
| 环境检查 | pwsh -File scripts/doctor.ps1 |
| 基础服务 | docker compose -f infra/compose.yaml up -d mysql postgres redis rocketmq-namesrv rocketmq-broker nacos provider-stub ※ |
| 整体启动（app profile 见下） | docker compose -f infra/compose.yaml --profile app up -d --build ※ |
| 观测启动（app profile 见下） | docker compose -f infra/compose.yaml --profile app --profile observability up -d --build ※ |
| Java单元 | .\java\mvnw.cmd -f java/pom.xml -B test |
| Java集成 | .\java\mvnw.cmd -f java/pom.xml -B verify -Pintegration |
| Python安装 | uv sync --project agent --frozen --all-extras |
| Python测试 | uv run --project agent pytest agent/tests/unit |
| Python格式/类型 | uv run --project agent ruff check agent/src agent/tests; uv run --project agent mypy agent/src |
| 契约检查 | pwsh -File scripts/verify.ps1 -Suite contracts |
| 冒烟 | pwsh -File scripts/verify.ps1 -Suite smoke |
| 系统测试 | pwsh -File scripts/verify.ps1 -Suite system |
| 故障实验 | pwsh -File scripts/verify.ps1 -Suite faults -Seed 42 |
| 性能实验 | pwsh -File scripts/verify.ps1 -Suite performance -Seed 42 |
| mock评测 | pwsh -File scripts/verify.ps1 -Suite agent-eval -Mode mock -Seed 42 |
| live评测 | pwsh -File scripts/verify.ps1 -Suite agent-eval -Mode live -Seed 42 |
| RAG评测 | pwsh -File scripts/verify.ps1 -Suite rag-eval -Mode live -Seed 42 |
| Harness结构/权限/上下文测试 | pwsh -File scripts/verify.ps1 -Suite harness -Mode mock -Seed 42 |
| 轨迹导出（合成run） | pwsh -File scripts/replay.ps1 -Action export -RunId <UUID> -Out <pack-directory> ※ |
| 严格回放（禁外网） | pwsh -File scripts/replay.ps1 -Action run -ReplayMode strict -Pack <pack-directory> ※ |
| 历史反事实回放 | pwsh -File scripts/replay.ps1 -Action run -ReplayMode counterfactual-recorded -Mode mock -Pack <pack-directory> -Variant <manifest-file> ※ |
| 合成世界反事实回放 | pwsh -File scripts/replay.ps1 -Action run -ReplayMode counterfactual-world -Mode mock -Pack <pack-directory> -Variant <manifest-file> ※ |
| 上下文消融 | pwsh -File scripts/verify.ps1 -Suite harness-eval -Mode live -Seed 42 |
| 全部无外部API验证 | pwsh -File scripts/verify.ps1 -Suite all-offline |
| 前端 | pnpm --dir web install --frozen-lockfile; pnpm --dir web test; pnpm --dir web build |

**尚未可执行的命令。** 上表描述的是终态契约；下列条目在其归属任务落地前会失败或为空操作，清单在此集中说明，避免实施时误以为是自己做错了：

- 基础服务命令中的 `provider-stub`（T12）：在此之前请省略该服务名。**不要为让命令通过而放一个不实现支付/物流协议的空占位服务**——假 stub 比失败的命令更有害。
- `--profile app`（T32 前服务镜像不完整）：当前为空操作，不会报错，也不会启动任何服务。
- `scripts/replay.ps1`（T38）：尚未创建。
- 各 `-Suite` 子命令（contracts T02、system T14、faults T29、performance/rag-eval T30、agent-eval T24/T31、harness T38、harness-eval T39）：未实现时 verify 入口以退出码 2 明确拒绝并指明归属任务，未知 suite 名退出 64，**都不会零步骤报成功**。

verify.ps1接受-Suite、-Mode、-Seed、-Case（单故障/测试case过滤）；输出实际子命令及报告路径。all-offline包含格式、单元、契约、系统mock，不默认跑live收费测试或重压测。

Harness命令在T35–T39对应任务落地，不假定T01已经实现所有子命令。all-offline最终必须包含H-CTX/H-RPL及mock自治/预算回归。replay export只读合成run且拒绝覆盖已有pack；run每次建立新evaluation_run_id与输出目录。counterfactual的-Mode live需要显式API配置与费用预算；strict拒绝live、忽略并禁止加载模型凭证。所有回放禁止业务写入，网络隔离由执行容器/受限出口配置实现并测试，不能只写一个布尔开关。

## 3. 代码约定

Java使用record DTO、显式业务枚举、构造注入、Flyway、MyBatis（不同时引入JPA）。共享状态变化全部在application事务边界；provider网络调用在事务外。示意：

```java
@Transactional
public Reservation reserve(ReserveCommand command) {
    var current = entitlementRepository.lockByLine(command.lineId());
    current.requireAvailableOrSameOperation(command.operationId());
    paymentRepository.reserveIfEnough(command.amountMinor());
    entitlementRepository.reserve(current, command);
    return Reservation.from(current, command);
}
```

示意仅说明事务位置，RESHIP不预留资金等细节必须服从domain-model，不能把示意当完整实现。金额不使用float/double；Clock注入；数据库更新检查影响行数。

Python使用Pydantic模型、类型标注、异步HTTP、显式timeout，禁止裸except吞掉取消。业务调用日志与图状态分开，异常分可重试/业务拒绝/权限拒绝。依赖由uv.lock管理。

UTF-8、中文文档、英文代码标识符。Java格式由Spotless，Python Ruff/mypy，前端TypeScript/ESLint。日志结构化JSON带trace_id；异常message不泄漏敏感参数。

## 4. 配置与迁移

每服务独立MySQL库和最低权限账号；一台MySQL容器承载多个schema不等于共享数据权限。PG agent账号仅访问agent_db。Flyway迁移追加，checkpointer迁移记录依赖版本。示例env仅给字段和非敏感默认值，真实.env与私钥忽略提交。

必须配置：DB连接、Redis、RocketMQ、Nacos、JWT issuer/audience/key location、模型endpoint/model/key、embedding revision、预算、provider stub模式。Nacos集中非敏感配置；密钥从环境/挂载读取。boot使用spring.config.import，禁止过时bootstrap配置。

测试/开发/lab profiles分别隔离库和provider，故障注入路由只在lab开放且有operator认证。doctor报告Docker/Java/Python/Node、可用内存、端口与镜像版本，不自动删除占用进程。

## 5. CI

PR流水线：格式+Java/Python单元+Schema/跨语言fixture -> 数据库与MQ集成 -> mock端到端 -> web build。nightly/manual运行故障矩阵、性能与live评测；API密钥只在受控环境，fork PR不能获取。

PR另跑小型strict golden packs、manifest hash/兼容性、关键事实保留、循环与预算停止测试。golden pack只含合成数据；变更快照必须提供首个差异原因，不能以“统一更新所有golden”掩盖行为变化。

provider-stub使用固定镜像WireMock持久扩展或轻量Python持久stub，最终固定为轻量Python+SQLite卷实现，测试支付/物流协议；网络故障由Toxiproxy或stub触发点实现。stub不计作核心微服务，不共享业务数据库。

测试报告包含跳过数，关键安全/资金测试不允许因依赖不可用而标通过。单元测试速度优先但不能用H2替代MySQL锁与唯一约束测试。

## 6. 每任务完成定义

当前用户故事正常路径与关键失败路径通过；契约无漂移；迁移可从空库执行；相关测试/格式通过；task记录有真实命令和结果；无秘密、无伪造指标。重型实验到对应阶段执行，不能为每次DTO改动重复全量压测。

## 7. 演示与发布

最终docs/demo.md提供6个演示：自动退款、损坏补证与审批、补发失败补偿、UNKNOWN退款对账、恶意材料越权拦截、Agent重启恢复。每个脚本写fixture ID、预期状态、查看证据位置。

v1.1再提供3个Harness演示：相同诉求不同证据下模型自主改变后续行动；长轨迹上下文裁剪与精确读回；历史失败包严格复现及变体首次分歧/REPLAY_MISS报告。共9个演示；回放命令在本地运行即可，不为此另建复杂前端。

默认本地部署，关闭时docker compose stop保留卷；清空实验数据必须限定lab项目与具名卷，显式用户确认后才可执行。框架不授权推送代码、购买云服务或公开发布演示实例。
