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
