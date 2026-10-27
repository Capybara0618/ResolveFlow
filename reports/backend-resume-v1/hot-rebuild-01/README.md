# 双实例热点重建：最小配对量化

2026-10-27用户只授权补充“热点重建次数由X降至Y”，不恢复原48/15/R120矩阵。复用已验证D4构建和v3探针，不改生产代码或原实验。

固定两个真实Commerce JVM共享本轮MySQL/Redis，默认10条评价页；B缓存开/锁关，C缓存开/锁开，除此之外相同。每组30请求，两个实例各15，3轮顺序BC/CB/BC，共180正式请求。每条件新namespace自然冷态，不阻塞SQL/回填、不注入故障、不自动重试。各实例先用不同商品预热客户端，随后确认热点key不存在。真实页面publicPage事件与operation=page计数器交叉核对；所有SQL（含每请求epoch）和成功/503/错误另外记录。

开发冒烟（独立hot-smoke-01）B30次/C1次，双方30成功/0拒绝/0错误；B实际SQL120/C33。冒烟第二实例只命中第一预热商品，为正式修正为各用不同商品，保证独立锁客户端初始化，并新增实际冷key验证。新源码2项目标检查与Ruff通过；先缺模块失败保留tmp/backend-hot-first-fail.log。正式3轮尚未执行，manifest与源/class/JAR/data hash先冻结。

正式命令：

```powershell
$env:PYTHONPATH='E:/Code/Agent+Backend/scripts'
agent/.venv/Scripts/python.exe -u -m evaluation.backend_hot_rebuild run --run-id 56a1dc2143e44062bda79849e82cac3c --cohort hot-formal-01
agent/.venv/Scripts/python.exe -m evaluation.backend_hot_rebuild audit --run-id 56a1dc2143e44062bda79849e82cac3c --cohort hot-formal-01
```

轮次已开始拒绝重跑，失败也保留；最终采用三轮重建次数中位数并同时列成功/拒绝。此次是同key自然冷缓存突发，不等同TTL/Redis故障/进程恢复或Gateway性能测量；D4功能证据复用。不改SQL既有成绩、Agent/PDF或第1/4/5冻结文本，0模型/费用/资金执行。

## 正式结果与收口

固定三轮一次执行完成，顺序BC/CB/BC；原始24文件见[rounds.zip](rounds.zip)，完整逐请求响应、页面加载/实际锁事件、前后SQL/服务计数均保留。独立[离线复算](audit.py)验证ZIP/hash、每轮30请求两实例各15、结果投影、重建事件与page计数、SQL差额、三轮中位数：3对/180请求全部正确、0个503/错误。

| 轮次 | B锁关重建次数 | C锁开重建次数 | B/C实际SQL执行数 | B/C成功响应 |
| --- | ---: | ---: | --- | --- |
| 0 | 15 | 1 | 75 / 33 | 30 / 30 |
| 1 | 30 | 1 | 120 / 33 | 30 / 30 |
| 2 | 30 | 1 | 120 / 33 | 30 / 30 |
| 中位数 | **30** | **1** | 120 / 33 | 30 / 30 |

每轮同时重建峰值B为8/16/16，C均1；加载窗口不等同同时SQL执行。每个请求先查epoch，页面重建另执行3条SQL，因此C仍有30+3=33条SQL。**重建次数中位数30→1（减少96.7%）不等同总SQL减少96.7%**，也不当Gateway延迟指标。第一轮B自然只有15次，原结果保持，未为凑30重跑；自然调度的逐轮波动不省略。

可写：“双实例30并发冷缓存突发下，热点重建次数由30次降至1次（3轮中位数）”。本组无人工门控且180请求全部成功，避免以更多拒绝制造少回源；只证明本地同key自然冷态突发，不泛化所有商品、负载、TTL到期或故障。D4功能验证继续复用，不扩矩阵。

实际运行/审计命令如上，退出均0；另执行 `agent/.venv/Scripts/python.exe reports/backend-resume-v1/hot-rebuild-01/audit.py` 独立从归档重算一致。自有双Commerce和MySQL/Redis关闭，PID空、全部观察端口关闭，数据卷/旧实验保持。简历[最终量化稿](../../../docs/resume-backend-query-cache-20261027.md)只追加此指标，原SQL数字保持；没有改个人PDF、Agent、第1/4/5冻结稿，0模型/费用/资金执行。本次到此收口。
