# 工程与命令 · v1.2核心

复用T00–T02已完成骨架和锁；不因为瘦身重建整个仓库。当前代码还未完成v1.2迁移，C00调整核心profile和契约选择；旧能力与目标能力分别说明。

## 1. 目录与风格

java/{gateway,case-service,commerce-service,shared-kernel}为核心；fulfillment-service留作旧骨架，默认不启动。agent/src/resolveflow/{api,runtime,harness,tools,policies,callbacks}沿用。contracts/core为C00新增目标；原contracts兼容基线保留。web保留轻量Vue界面，reports只放真实证据。

Java record DTO、构造注入、MyBatis、Flyway、显式application事务，金额不用float，Clock可注入。Python Pydantic、类型标注、明确timeout与取消、mock/live ModelClient，Ruff/mypy及uv.lock。已有风格不为重构而重构。

示例事务边界（不是完整代码）：

```java
@Transactional
public RefundOperation accept(RefundCommand command) {
    var previous = operations.find(command.operationId());
    if (previous != null) return previous.requireSamePayload(command.payloadHash());
    ledger.reserveUnderLock(command);
    return operations.createWithOutbox(command);
}
```

真实实现必须在同事务处理inbox、金额/行占用及唯一键；provider网络调用在事务外，不照抄示例省略约束。

## 2. 当前可运行入口

下列入口已有实现，历史结果见todo与reports；本轮文档修订不代表全部重跑。工作目录仓库根：

| 用途 | 命令 |
| --- | --- |
| 环境 | pwsh -File scripts/doctor.ps1 |
| 格式 | pwsh -File scripts/verify.ps1 -Suite format |
| 单元 | pwsh -File scripts/verify.ps1 -Suite unit |
| 契约 | pwsh -File scripts/verify.ps1 -Suite contracts |
| 当前离线集 | pwsh -File scripts/verify.ps1 -Suite all-offline |
| Python针对性 | uv run --project agent --frozen pytest agent/tests/unit -q |
| Java契约 | .\java\mvnw.cmd -f java/pom.xml -B -pl shared-kernel -am test |
| 前端 | pnpm --dir web test |

当前all-offline包含真实服务smoke和基础设施依赖，不等于不需要Docker；它只表示不使用外部付费模型API。核心选择已调整（C00.3）：`verify.ps1 -Suite smoke`默认`-Profile core`，只启动gateway/commerce/case与Agent，不启动fulfillment与Nacos；`-Profile compat`保留旧的完整入口，旧断言一条未删。启动集合来自`contracts/core/profile.json`，不在脚本里再写一份。

## 3. 尚未实现的目标入口

| 用途 | 命令 | 归属 |
| --- | --- | --- |
| 核心启动 | docker compose -f infra/compose.yaml --profile core up -d --build | C00选型、C11完整落地 |
| 退款系统测试 | pwsh -File scripts/verify.ps1 -Suite system -Mode mock | C05/C08 |
| Harness回归 | pwsh -File scripts/verify.ps1 -Suite harness -Mode mock | C08–C10 |
| 轨迹导出 | pwsh -File scripts/replay.ps1 -Action export -RunId <UUID> -Out <directory> | C10 |
| 严格回放 | pwsh -File scripts/replay.ps1 -Action run -ReplayMode strict -Pack <directory> | C10 |
| 核心故障 | pwsh -File scripts/verify.ps1 -Suite faults -Seed 42 | C12 |
| 真实模型对照 | pwsh -File scripts/verify.ps1 -Suite agent-eval -Mode live -Seed 42 | C12 |
| 检索对照 | pwsh -File scripts/verify.ps1 -Suite rag-eval -Mode live -Seed 42 | C07/C12 |
| 查询性能 | pwsh -File scripts/verify.ps1 -Suite performance -Seed 42 | C11/C12 |

默认未实现suite退出2、未知suite退出64，不得零步骤成功。-Case支持按case过滤由归属任务实现；不存在脚本/容器时不放空stub凑启动。旧harness-eval、反事实命令标DEFERRED，不是核心交付门槛。

## 4. 核心资源与安全

MySQL的Case/Commerce独立schema/账号；PG Agent账户只访问agent_db；Redis不是授权事实。RocketMQ用核心v2 topics。core profile不依赖Nacos/Sentinel/完整观测容器；保留锁与可选配置，避免全量换栈。

### 演示账号（C03.2b-1 补记）

口令只以 PBKDF2 哈希存在 `DemoAccounts` 里，仓库文档此前没有列出；下表是**按哈希逐个验证过**的口令（不是按命名猜的），跑真实端到端要登录时用得上。它们只是演示凭据，正式部署应换掉并轮换 JWT 密钥。

| 用户名 | 商户/客户 | 角色 | 口令 |
| --- | --- | --- | --- |
| demo-customer | M-1001 / C-2002 | CUSTOMER | demo-pass-1001 |
| demo-customer-2 | M-1001 / C-2003 | CUSTOMER | demo-pass-1002 |
| demo-reviewer | M-1001 | REVIEWER | demo-pass-1003 |
| demo-operator | M-1001 | OPERATOR | demo-pass-3001 |
| demo-customer-m2 | M-1002 / C-2004 | CUSTOMER | demo-pass-2001 |
| demo-reviewer-m2 | M-1002 | REVIEWER | demo-pass-2002 |

provider-stub在C04落地轻量Python+SQLite持久模拟退款，含幂等/故障注入，不实现物流写协议。物流只读适配内置Commerce；版本化合成资料可从fixtures加载。

秘密不入库/日志/报告；.env不提交。故障路由仅lab且受控。数据库迁移只追加；旧履约库和卷不因停用被删除。关闭用compose stop保留卷，不授权清库、Git历史重写、推送、购买或公网发布。

## 5. CI与完成定义

每子步先关键失败测试，再实现、验证、记录；通常3–5核心文件，过大先拆。CI覆盖现有兼容+核心契约、格式、单元、关键DB/MQ集成、mock闭环、strict小包、web build，不默认付费/重压测。

每完成项记录实际命令/日期/文件/报告/失败与未运行。允许任务含多子步，但不能只生成所有代码最后才跑。核心完成标准以core-scope/evaluation为准，不被旧T任务清单重新扩大。
