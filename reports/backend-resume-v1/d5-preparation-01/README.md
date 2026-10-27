# D5：隔离数据与 SQL 计量准备

2026-10-26 开始，2026-10-27 Docker 恢复后核验。此小步未产生正式 HTTP 性能指标，不替代 48 个正常窗口、15 个故障窗口或 R120。

## 已验证

- 隔离 run `56a1dc2143e44062bda79849e82cac3c`，仅本轮带归属标签的 MySQL/Redis；未启动 MQ、Agent 或退款执行器，原业务卷保留。
- D0 原始 JAR 与 D4 候选 JAR 逐字节复制并解包原 class/lib，用独立 `D5Probe` 启动；应用代码不重新编译。JDBC execute 计数包含身份、epoch 与页面查询，SQL inflight 与页面加载事件分别记录。探针只绑定 loopback，控制请求校验本轮 ID，不打入生产 JAR。
- seed42：20000 工单（4000 待审）、10000 已付订单、2000 未付草稿、30 商品/45 SKU/6000 条评价。外键及 CHECK 保持启用，金额差额与评价签收资格异常均为 0。它们是直接构造的合成读模型，未执行真实支付或退款；待支付到期时间专供稳定查询，不代表创建接口生成的数据。
- 生成器已有开始标记，拒绝覆盖或重播。数据 SQL/oracle/hash 在本轮 tmp 留存，Docker 重启后实际工单 20000、评价 6000 保持。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_d5_runtime.py -q`：4 passed；三个新 Python 文件 Ruff 通过。

## 证据与失败

本机忽略目录 `tmp/backend-resume-v1/56a1dc2143e44062bda79849e82cac3c` 留有 `d5-builds.json`、`dataset-started.json`、`dataset.sql`、`dataset-oracle.json`、`dataset-checked.json`、探针 class/源快照及进程日志。数据 SQL SHA256 `3ae0335611ea636b3414caf5d82cefec81142391886589564eab5c000795b337`，oracle SHA256 `6fed2d352b6055673bca7661fe43ee84c75841e45141149f33c692eb0e68475f`。

首次 Commerce 启动/计量成功，Case 因本机 SocketException（No buffer space available）启动失败；同一冻结构建单独重试成功，探针记录 23 条启动 SQL。尚未证实底层原因，不归因为外网。首次失败日志保留；没有正式轮被重跑。Docker 重启后按归属恢复原容器，未重新生成数据。恢复检查中一次误用旧表名的只读等待未成功，随后按实际 aftersale_case 表核验。

## 下一小步

实现并冒烟固定流量、逐请求正确性、双 Commerce 分流及故障注入、离线审计；修正开发探针门控的多加载标记语义，再冻结新的执行器/探针版本。当前源快照不覆盖。完成正式 manifest 后才一次执行约定矩阵，错误、超时、拒绝和未触发故障都保留分母。简历第 4/5 条及 Agent/PDF 冻结不动。
