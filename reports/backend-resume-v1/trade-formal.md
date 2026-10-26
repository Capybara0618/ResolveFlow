# D1正式交易矩阵：160轮完成与源审

2026-10-26。运行器接线提交`2f5a334`普通推送核实后，冻结`matrix-formal-01`并一次执行既定矩阵，未修改源码、补跑或替换失败轮。此前开发轮和10轮wiring不进入本批分母。仍为D0独立环境与原冻结Java JAR，未修改生产业务/迁移、Agent侧或简历，0模型/费用。

## 结果与准确分母

**8类×10/30两档×每档10轮，共160/160通过；3200个选定场景请求，10并发与30并发各80轮。**每轮不只核对线程数：释放实验锁前观察全部客户端到达，结束后独立验证全部C个实际start/end区间有共同交集，最小交集5.3062ms。该数只证明重叠，不是接口延迟或吞吐指标。

| 场景 | 轮数/选定请求 | 主要核对 | 成功付款组 |
| --- | --- | --- | --- |
| T01 同revision修改购物车 | 20/400 | 恰一赢家，revision仅+1，保存数量对应赢家 | 0 |
| T02 同key两份有效结算载荷 | 20/400 | 一行/两行均可在原购物车上有效；绑定赢家、另一载荷冲突，原载荷重放/快照一致 | 0 |
| T03 结算与商品更新 | 20/400 | 两顺序各10轮，价格/规格/下架轮换；旧/新快照完整，先下架明确404 | 0 |
| T04 同草稿同付款key | 20/400 | 并发重放仍同一attempt/收据/订单 | 20 |
| T05 同草稿不同付款key | 20/400 | 恰一尝试获得付款资格，其余明确冲突 | 20 |
| T06 成功响应真实丢失 | 20/400 | 代理读到上游200后断开，原key恢复与原attempt一致 | 20 |
| T07 收据已存、订单未发布时真实终止 | 20/400 | 退出前一收据/零订单；重启原JAR后沿原attempt及预定order_id发布 | 20 |
| T08 到期关单与付款 | 20/400 | 两顺序各10轮；关单先无资金效果，预留先继续原尝试 | 10 |
| 合计 | **160/3200** | **无失败轮、无未到达窗口、无缺失完成记录** | **90** |

独立终态SQL复核：90个成功模拟付款组对应**90个订单、90份成功收据、90个attempt、180条订单行、180个退款槽**。每组草稿/收据/行金额/账本均52800分，预留/已退0。全局订单/成功收据/尝试集合差分与各轮集合并集完全一致，没有预期ID以外的旁生效果；**重复订单0、重复成功模拟收据0**。这是模拟提供方的幂等收据口径，不将HTTP调用次数当作扣款次数。

选定3200响应：200=1840、409=1280、下架404 NOT_FOUND=80。全部准备/查询/故障首请求共有4256条完整记录：200=2816、409=1300、201=20、404=80、丢响应status0=20、崩溃首请求503=20。后两类40次真实故障首请求单列保留，不能称“全部HTTP零失败”；没有意外响应或未记录尾部。业务UNKNOWN窗口与评测记录缺失是两种状态，本批实际观察了前者，不存在后者。

## 证据与复算

- [执行manifest](matrix-formal-01/manifest.json)：固定160轮、源码/JAR hash、原wiring先决条件及调度参数；源码副本在完整包内。T08关单先用2秒调度，预留先用10秒准备窗口，逐轮重启明确配置；不以此计算自然恢复速度。
- [原summary](matrix-formal-01/summary.json)、[独立复算](matrix-formal-01/audit.json)、[终态SQL数据](matrix-formal-01/database-audit.json)：共同核对轮次、全部C区间共同交集、主体、原请求hash、资金实体和金额；审计不靠summary计数直接判通过。
- [完整原字节包](matrix-formal-01/evidence.tar.xz)、[逐文件索引](matrix-formal-01/archive-index.json)：10004文件，包含全部intent/completed、故障窗口、原始结果、逐轮outcome、阶段checkpoint和执行源码；归档后重新逐文件读取并验证hash。原本地目录仍保留，不提交数据库文件/凭据/原始进程日志。
- [离线审计程序](matrix-formal-01/audit.py)只读完整包，独立用`min(end)>max(start)`核对所有C请求重叠；[数据库采集程序](matrix-formal-01/collect_database.py)只执行SELECT并检查run归属，用于运行环境尚在时采集终态。

实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_matrix.py freeze --run-id c5265fe48bc946ec99398450c998a014 --matrix-id matrix-formal-01 --profile formal
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade_matrix.py execute --run-id c5265fe48bc946ec99398450c998a014 --matrix-id matrix-formal-01
agent/.venv/Scripts/python.exe reports/backend-resume-v1/matrix-formal-01/collect_database.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/trade-matrices/matrix-formal-01
agent/.venv/Scripts/python.exe reports/backend-resume-v1/matrix-formal-01/audit.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/trade-matrices/matrix-formal-01 reports/backend-resume-v1/matrix-formal-01/audit.json
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py stop --run-id c5265fe48bc946ec99398450c998a014
```

既有输出禁止直接覆盖；重新审计应解压到索引raw_directory并使用新的输出文件名。测试环境收尾保留容器及数据卷，退出/端口核对见[停止记录](matrix-formal-01/stopped.json)。运行器本批相关59检查通过、1条既有弃用警告；正式执行后只新增两份只读审计程序并实际运行、Ruff通过，没有为了重复验证而重做付款或重跑Java全回归。

## 简历可用口径与下一步

第4条量化可用：**“在最高30并发、8类160轮竞争测试中，90个模拟付款组未出现重复订单或重复扣款。”**正文机制继续对应版本/行锁、服务端报价、幂等付款、订单与账本同事务，以及原请求恢复。暂不改PDF，待其余后端条目完成后统一填数。

本批为本机单Commerce实例、同一演示买家/店铺的共享目标竞争；没有独立目标吞吐、真实支付或高可用指标。下一步进入D2版本授权与异步退款，另测RocketMQ重复/停机、UNKNOWN金额占用和结果Outbox崩溃窗口；D1付款恢复不能替代退款故障结果。D3订单批量查询和D4 Redisson/性能也未完成。
