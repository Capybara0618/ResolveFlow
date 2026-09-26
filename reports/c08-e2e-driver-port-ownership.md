# C08真实联调前的端口所有权保护（2026-09-26）

现有 `e2e_refund_chain.py` 与 `e2e_harness_java_tools.py` 在Java服务端口被占用时会按端口强制结束PID；脚本结束时也会结束届时占用端口的PID，即使该进程不是脚本启动的。共享工作区不能用此行为启动C08真实联调。

两个脚本现在先检查8083/8081；已占用时记录PID并退出，不创建演示订单，也不启动Java服务。清理只终止脚本自己持有的 `Popen` 子进程；退出后如端口仍被占用，仅提示，不对端口所有者执行 `taskkill`。未修改共享底层 `e2e_transport_refund.py`，本步不运行该旧驱动。

验证（工作目录 `agent/`）：

- RED：`python -m pytest tests/unit/test_e2e_driver_process_ownership.py -q -p no:cacheprovider --tb=short` → **4 failed**；两脚本无占用拒绝函数，`stop(None, port)` 均调用按端口杀进程。
- GREEN：同命令 → **4 passed**，模拟未知PID占用，确认拒绝且不会调用杀进程函数；`python -m py_compile ../scripts/e2e_refund_chain.py ../scripts/e2e_harness_java_tools.py` 通过。
- `python -m ruff check tests/unit/test_e2e_driver_process_ownership.py` 通过。两旧脚本整体Ruff仍报告**44个既有规则违规**（密码字面量、旧字符串注解、SQL拼接等）；本步新增函数的两处注解违规已修复，未将旧脚本整体lint写成通过。
- `git diff --check` 通过。

未运行真实Java/Agent联调、全量Python、Java测试/Spotless、all-offline、live模型。保护只覆盖这两个C08准备使用的驱动；其他旧驱动仍需各自检查。下一步构造或改造真实C08端到端驱动，验证Case派发到常驻Agent、MCP读取、回调、审批和模拟退款，并把失败点定位到具体边界。
