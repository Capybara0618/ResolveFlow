# D1.4：逐请求持久记录与并发实测接线

2026-10-26。独立环境、原冻结Java JAR。新增请求记录器并接入既有HTTP准备/读取与burst，不修改业务实现。每个发送意图在调用前独立写入并fsync，每个响应返回后独立保存实际起止时间、主体标签、key/载荷hash及结果。登录请求、密码、Bearer不入记录；主体通过内存中的演示账号映射。

新增6检查先缺模块失败，包含真实子进程os._exit(73)：前一响应仍可读取，后一条只有意图时明确UNKNOWN。只读恢复对象不能准备/发送请求；截断或身份/hash不匹配的完成记录拒绝，区间首尾相接不算并发。最终相关55通过、1条旧Starlette弃用警告，Ruff通过。

真实T04同key付款30请求：[执行manifest](c5265fe48bc946ec99398450c998a014/journal-probes/request-journal-01/manifest.json)、[只读恢复审计](c5265fe48bc946ec99398450c998a014/journal-probes/request-journal-01/audit-recovered.json)。共37条独立完整业务请求记录，其中30付款请求均200；按请求实际start/end区间扫描，最大同时在途为30。自有测试库草稿行锁在全部客户端到达后释放，不能据此报告自然负载吞吐或接口延迟收益。最终一个attempt/收据/订单、两行/槽，金额52800分一致，预留/已退0。

首次付款与独立记录已完成，但离线audit按Windows默认GBK读取UTF-8中文失败。保留当时全部执行源码hash/快照及请求，新增中文反例先失败，统一显式UTF-8后用--audit-only只读核对，发送数0，原文件hash全部保持。不得为了修审计重做这一付款。首次失败原日志留忽略tmp，未把它算业务失败或偷偷替换输出。

实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py resume --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/evaluation/trade_journal_probe.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id request-journal-01
agent/.venv/Scripts/python.exe scripts/evaluation/trade_journal_probe.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id request-journal-01 --audit-only
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_trade_request_journal.py agent/tests/unit/test_backend_trade_probe.py agent/tests/unit/test_backend_trade_faults.py agent/tests/unit/test_backend_trade_boundaries.py agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q
agent/.venv/Scripts/ruff.exe check scripts/evaluation/trade_journal_probe.py scripts/evaluation/trade_request_journal.py scripts/evaluation/backend_trade.py scripts/evaluation/backend_smoke.py agent/tests/unit/test_trade_request_journal.py
```

当前只接线一轮T04，160轮正式矩阵未运行；其他场景仍需统一接入并发门控、失败分类与冻结入口。业务/Agent侧/旧报告/四个历史脏文件保留，0模型/费用。
