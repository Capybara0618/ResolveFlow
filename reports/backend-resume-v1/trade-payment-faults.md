# D1.2：付款响应丢失与真实进程崩溃预检

2026-10-26。独立环境 `c5265fe48bc946ec99398450c998a014`，沿用D0冻结的三个JAR；业务实现、原数据、Agent侧三条及简历未改。这里是T06/T07各10、30并发一轮的4轮开发预检，不是160轮正式交易矩阵。

## 实际结果

| 场景 | 两并发档结果 | 窗口直接证据 |
| --- | --- | --- |
| T06 公共HTTP响应丢失 | 2/2轮通过，40次原key恢复全部200 | 独立loopback HTTP代理已读到上游200及393字节响应，关闭socket不发响应；两次客户端均RemoteDisconnected |
| T07 收据已存、订单未发布时退出 | 2/2轮通过，40次原key恢复全部200 | 退出前均为一attempt、一收据、零订单，draft=PAYMENT_PENDING、attempt=UNKNOWN；真实终止Commerce且端口关闭，随后以相同冻结JAR和原数据库重启 |

四组最终各一个attempt、一个成功收据、一个订单、两行及两个退款槽；草稿、收据、订单行和账本金额均52800分，预留/已退均0。T07恢复的attempt和预定order_id与退出前相同。真实调度保持开启，未分别归因哪一请求或调度赢得发布。

两个崩溃时的首次HTTP请求均503，作为**预定故障窗口的中断结果**单列，不能算80次恢复中的错误，也不能把整批说成HTTP零失败。T06两个丢响应也单列。原[基础预检](trade-preflight.md)8轮160请求不改，本步另有80恢复请求、4次首次付款请求。

## 门控、失败及验证

[运行器](../../scripts/evaluation/backend_trade_faults.py)只连接带本run标签的测试MySQL：先锁收据表阻止provider提交；待预留事务提交后另连接锁草稿行，再释放收据表锁，确认收据提交而发布仍受阻，保存状态后终止自有Commerce PID。连接关闭回滚释放门控。没有写入成功状态、替换provider、改生产接口或触碰原业务数据库。实验期间整张模拟收据表受锁，适用于独立故障实验，不适合业务环境。

3个新失败用例先因缺模块失败，之后与原相关测试共46通过、1条既有Starlette弃用警告；Ruff通过。生产JAR未变，未重跑Java全回归。第一次运行在login前遇ConnectionRefused：上一中断后Java子进程已退出而Docker仍在；恢复原环境后用新probe目录执行，空的首目录未覆盖、无付款发生。实际4轮的原始结构化证据见[summary](c5265fe48bc946ec99398450c998a014/trade-faults/d1-payment-faults-02/summary.json)，凭据/原日志只留忽略tmp。

实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py resume --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_faults.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-payment-faults-02
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_trade_faults.py agent/tests/unit/test_backend_trade_probe.py agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q
agent/.venv/Scripts/ruff.exe check scripts/evaluation/backend_trade_faults.py scripts/backend_resume_lab.py agent/tests/unit/test_backend_trade_faults.py
```

T03商品更新、T08到期竞争、正式轮次、D2授权退款故障、D3批量查询及D4 Redisson仍需独立完成；本步不填简历量化数字。
