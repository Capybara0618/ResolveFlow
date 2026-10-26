# D1.3：商品快照与到期付款边界预检

2026-10-26。只在原D0独立环境和冻结Java JAR上新增测试工具；业务代码、迁移、Agent侧及简历未改。商品写入和购物/付款均走实际Gateway/Case/Commerce，关单和对账由实际Java调度执行，没有直接写入成功/关闭状态。

## 已完成的开发证据

| 范围 | 通过轮数 | 结果 |
| --- | --- | --- |
| T03 价格/规格/下架 × 两个顺序 × 请求数10/30 | 12 | 先结算接受完整旧快照；先更新拒绝旧版本，价格/规格更新后另一次确认接受完整新快照；先下架返回404 NOT_FOUND |
| T03 加强门控的价格双顺序，请求数10 | 2 | 具体观察第二个业务SQL被第一个事务阻塞，再放行；不是把同一burst其他购物车等待误当商品更新等待 |
| T08 到期关单先提交，请求数10/30 | 2 | 真实Java关单先排队，付款随后等待；最终CANCELLED/EXPIRED、40次付款409、无attempt/收据/订单 |
| T08 付款先预留，请求数10/30 | 2 | 截止时间已过仍PAYMENT_PENDING；从reconcile_count=0到实际调度领取原attempt，最终各一收据/订单、两行/槽、52800分一致，未被关单 |

本步**18轮通过，340次场景请求：200为170、409为130、404为40**。另有7轮准备失败/窗口未到达，全部保留，不计入18个通过轮，也不隐去其业务效果。失败轮的3个付款组最终也各一attempt/收据/订单，不能因客户端记录不完整而重新发送。统一[审计及最终数据库核对](c5265fe48bc946ec99398450c998a014/trade-boundaries/audit.json)关联所有原输出hash；原summary及续接前文件保持。

开发轮的10/30是该轮请求数量。付款先预留和加强的结算先提交轮采用“1个请求建立窗口，再放行其余C−1”的分阶段门控，**尚未逐轮验算C个请求同时在途**，不把本批称为正式30并发成绩。正式矩阵仍须统一配置、冻结工具、逐请求落盘及根据时间区间核验并发；不能拿本批轮数填简历。

## 发现和修正

1. 首两轮只观察子表元数据等待，未识别LOCK TABLES经外键导致父表checkout_draft插入等待。原key只读核对均一草稿/无付款；调整为观察实际INSERT语句，没有重新发送原轮。
2. 第三目录先完成10轮，旧断言把先下架404误当应为409。修正只读验证该轮原请求及原key零草稿，再完成缺失轮；旧10轮与summary hash保持。下架404只接受NOT_FOUND，500等仍失败。
3. 首次到期夹具用“现在减1秒”，新草稿创建不足1秒时违反expires_at>created_at。改为created_at+1微秒，保留建单记录，未修改创建时间或资金状态。
4. 把整组付款堵在模拟收据表上会占用全部JDBC连接，后台对账无法领取；加强商品门控时也遇到同类问题。改为先建立窗口、证明第二业务方/调度到达，再放行剩余请求；不把实验性长表锁下的池耗尽宣传为生产资金缺陷。
5. 付款先预留30请求时，调度曾提前领取，按NOT_REACHED保留；辅助过期行锁方案又影响预留，也保留。最终只对该类实验重启自有Commerce、显式配置10秒调度初始间隔，再在真实调度开始前建立预留/过期状态；默认仍2秒。10秒是lab参数，JAR未变，不作恢复速度指标。没有反复重发同一付款或删失败轮求满分。

两项新增检查先因缺模块失败，404细化检查先因缺函数失败；最终相关**49通过、1条既有弃用警告，Ruff通过**，未重跑Java全回归。核心新增为[边界运行器](../../scripts/evaluation/backend_trade_boundaries.py)及其测试，实验启动器只新增有界调度参数；实际执行版本随各目录保存，后续修工具不覆盖旧hash。

实际运行目录：`d1-boundaries-01/02/03`（第三目录一次--resume）、`d1-expiry-01/02/03/04`、`d1-catalog-gates-01/02`。主要入口及最终集中验证：

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_boundaries.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-boundaries-03 --resume
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_boundaries.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-catalog-gates-02 --only catalog --catalog-factor price --concurrency 10
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_boundaries.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-expiry-04 --only expiry --expiry-order reserve-first --concurrency 30
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_trade_boundaries.py agent/tests/unit/test_backend_trade_faults.py agent/tests/unit/test_backend_trade_probe.py agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q
agent/.venv/Scripts/ruff.exe check scripts/evaluation/backend_trade_boundaries.py scripts/backend_resume_lab.py agent/tests/unit/test_backend_trade_boundaries.py
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py stop --run-id c5265fe48bc946ec99398450c998a014
```

这些是本次已执行命令，既有目录禁止直接重跑覆盖。后续正式评测需新输出目录和冻结manifest。D1八类开发场景已有证据，160轮正式矩阵、D2退款故障、D3批量查询、D4 Redisson及性能尚未完成。
