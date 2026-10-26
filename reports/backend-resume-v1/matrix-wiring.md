# D1.5：正式交易运行器接线验收

2026-10-26。逐请求记录提交5fb0dbc后，将八类场景接入同一冻结入口。独立真实Gateway/Case/Commerce/MySQL/MQ及原冻结JAR，0模型/收费。新增[运行器](../../scripts/evaluation/backend_trade_matrix.py)的formal计划为8类×10/30两档×10轮=160；正式冻结必须先有相同源码/JAR的全部接线通过结果，不能零步骤成功。

本次仅执行wiring：8类、T03/T08各补反向顺序，共10轮、每轮30个场景请求；**10/10通过，实际区间峰值每轮均30**。300个场景响应200=167、409=133；全部准备/查询/初始故障共367条完整独立记录。5个成功付款组各一attempt/成功收据/订单，两行/槽、52800分一致；每轮对比全局订单/成功收据/尝试ID集合，防止只查预期order_id漏掉额外效果。

T02改为原购物车上均有效的“一行/两行”载荷，谁先绑定key都可胜，另一份明确冲突，并核对真实快照及原载荷重放；旧改数量用例会因购物车不匹配独立失败，不能充分证明key绑定。T03/T08放行前等待全部C个客户端已到达；其余场景以自有库行锁控制释放，再用完成记录实际区间复算，门控等待不作为性能指标。T06首次丢响应、T07首次503和故障窗口单列，峰值仅核对选定C个竞争/恢复请求。

正式矩阵支持按manifest续接：完整轮只验证原hash，已有成功业务结果可只读补计分；无完整结果的已开始轮拒绝重发，原未知请求保留。实际对本次10轮执行resume，原文件及业务集合保持，新增业务意图0，仅重新登录获取临时身份。证据按原字节压缩保存于[完整包](matrix-wiring-01/evidence.zip)，逐文件hash及ZIP hash见[索引](matrix-wiring-01/archive-index.json)，另有[manifest](matrix-wiring-01/manifest.json)、[summary](matrix-wiring-01/summary.json)、[续接审计](matrix-wiring-01/resume-audit.json)。解压到索引raw_directory可还原原布局；原目录仍在本机保留，无数据库文件/凭据/模型请求。

新4检查先缺函数/模块失败，最终相关59通过、1条旧弃用警告，Ruff通过；无生产代码/迁移改动，未重跑Java全回归。实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_matrix.py freeze --run-id c5265fe48bc946ec99398450c998a014 --matrix-id matrix-wiring-01 --profile wiring
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_matrix.py execute --run-id c5265fe48bc946ec99398450c998a014 --matrix-id matrix-wiring-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_matrix.py resume --run-id c5265fe48bc946ec99398450c998a014 --matrix-id matrix-wiring-01
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_trade_matrix.py agent/tests/unit/test_trade_request_journal.py agent/tests/unit/test_backend_trade_probe.py agent/tests/unit/test_backend_trade_boundaries.py agent/tests/unit/test_backend_trade_faults.py agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q
agent/.venv/Scripts/ruff.exe check scripts/evaluation/backend_trade_matrix.py scripts/evaluation/backend_trade.py scripts/evaluation/backend_trade_boundaries.py scripts/evaluation/backend_trade_faults.py agent/tests/unit/test_backend_trade_matrix.py
```

本提交后冻结相同源码/JAR的新formal目录，只执行既定160轮一次，失败/未到达/UNKNOWN保留，不拿开发或wiring轮数混入正式分母。D2退款故障、D3查询和D4 Redisson/性能仍未完成。
