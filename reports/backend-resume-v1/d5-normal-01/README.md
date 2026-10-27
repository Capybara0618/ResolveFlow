# D5 正式正常 HTTP 矩阵

2026-10-27，准备提交573dbe8c，run `56a1dc2143e44062bda79849e82cac3c`。manifest绑定旧/新JAR、数据、执行器/评分器、v3探针、端口和48窗口。完整请求集183变体，旧/新投影一致；八开发组合验证见准备报告。

正式命令（不调用模型或退款）：

```powershell
$env:PYTHONPATH='E:/Code/Agent+Backend/scripts'
agent/.venv/Scripts/python.exe -u -m evaluation.backend_d5_normal run --run-id 56a1dc2143e44062bda79849e82cac3c --cohort normal-v1
agent/.venv/Scripts/python.exe -m evaluation.backend_d5_normal audit --run-id 56a1dc2143e44062bda79849e82cac3c --cohort normal-v1
```

每窗30秒预热+60秒正式，10/30并发，各三轮，顺序预定；只读取本轮隔离合成库。P1原SQL/索引无新增变化，P2比较真实订单批量化，P3双Commerce固定轮转。每窗记录冷读、预热和正式全部请求、SQL/路由前后快照；错误及503保留。原始gzip在同run/normal-v1，各完整窗口只执行一次，缺complete拒绝自动重跑；最终归档审计后补结果，当前尚无正式成绩。

此批仅正常48窗口。15故障与R120独立冻结后执行；不把开发冷态1成功9拒绝算成正式互斥收益，不改第4/5条与Agent/PDF冻结。
