# 真实服务退款故障：60/60通过

2026-10-07。Case/Commerce两个Java进程、真实MySQL3307、专用RocketMQ9879/10916，持久SQLite模拟支付provider与真实loopback HTTP。专用合成订单schema resume_refund_case_20261007c / resume_refund_commerce_20261007c，原业务库与既有消息不清理。付款是假支付，成功记录是模拟provider持久交易，不是现实资金交易。

| 场景 | 固定故障操作 | 通过 | 全流程平均/最大秒 |
| --- | --- | --- | --- |
| F1 | 原签名命令重复投递10次 | 10/10 | 9.614 / 11.359 |
| F2 | 同一已审批操作，10个不同event_id并发投递 | 10/10 | 9.555 / 10.984 |
| F3 | 同订单两个商品行并发退款 | 10/10 | 9.980 / 12.906 |
| F4 | provider持久成功后实际断开HTTP，不发送响应；查询可见性延后10秒 | 10/10 | 36.836 / 37.312 |
| F5 | Commerce已结算、结果Outbox仍PENDING时kill真实进程，再启动 | 10/10 | 24.441 / 24.906 |
| F6 | 原成功结果共投递10次，等待inbox.deliveries=10 | 10/10 | 14.597 / 16.110 |

合计60次故障、70个成功退款商品行（F3每次两行），每行provider独立成功交易数均1、Case关闭本地事件均1；重复成功退款0、190个预留/UNKNOWN/结算/最终账本边界的超额订单0、最大超额0分、错误RefundFailed结果0。F4全部10次观察到UNKNOWN，保留2599分占用且不换operation_id，HTTP记录显示查询原操作后成功结算，收敛10/10。F5均验证结算后未发布状态并真实kill；恢复只发布持久结果，不重复退款。全流程耗时包含批准、MQ、故障及重启等待，不等于纯资金API延迟。

## 接线与证据

通过Case公共HTTP登录、工单、复核proposal、批准及消费接口取得真实签名RefundRequested Outbox。为固定投递次数/竞争窗口，实验关闭Case自动outbox投递，由Java21 source-file sender读取原事件（F2仅生成新event_id并按同一公开测试密钥签名）发送真实MQ；Commerce真实consumer/账本/worker/provider结算/Outbox以及Case真实result inbox/投影完整执行。Case审批时的人工proposal与证据hash为显式合成fixture，不将本矩阵称为LLM决策准确率。Commerce Outbox正常运行，只有F5暂时关闭以固定崩溃窗口。

provider在实际请求到达后先等待实验gate；读回预留边界再放开。F4在持久成功后shutdown/close真实socket，保留同幂等操作记录；不是把HTTP响应体写成假UNKNOWN。F2十条同操作消息并发，不是十份不同审批；跨授权同行拒绝及账本并发另见既有真实MySQL测试。

[正式原始矩阵](formal-v1/results.json)保存订单/行/工单/操作标识、190个账本快照、provider HTTP方法/操作号、每行成功计数、关闭事件数及所有失败；本轮60无失败。[metadata](formal-v1/metadata.json)冻结双方jar与三个执行源hash。[summary](summary.json)绑定70份消息JSON、原始结果和计算脚本hash。执行器断言F6十次inbox投递、F5未发送结果及每行/Case一次；日志与模拟provider SQLite仅留本地tmp，不提交数据库快照或原始进程日志。

## 开发试跑与发现的真实修复

开发失败记录保留，未进入正式60分母：trial-v1缺政策导入导致422，并发现原demo broker历史消息会重放到新消费组；改为新建专用broker，保留旧broker/数据。trial-v2修正Outbox实际列/事件类型。trial-v3首类通过后发现同行同操作竞争会误发ANOTHER_OPERATION_LIVE，且同步等待sender退出拖住provider gate、产生非预期HTTP超时；同时真正成功后HTTP响应头EOF未按UNKNOWN处理。trial-v4复用试跑broker新组再次读取旧消息，保留结果并使用全新v2专用broker和新c schema。[trial-v5](trial-v5/results.json)6/6代表故障通过后冻结正式版本。

两个生产修复已分别以真实失败反例确认：ledger锁后用同事务current-read重查同operation并复用receipt；provider包装IOException/ResourceAccessException转UNKNOWN，其他异常沿原行为。[修复报告](fixes/README.md)及4类28项验证均通过。没有削弱授权/金额约束或删除旧断言；原脏测试文件未夹带。

正式命令：`python scripts/resume_refund_benchmark.py --output reports/resume-quantification-v1/refund/formal-v1`；不可覆盖已有输出。已准备专用schema和broker，只用已存在依赖镜像。`python scripts/resume_refund_summary.py`只读取资产，断言完整6×10、source/jar hash、UNKNOWN原操作查询及资金快照，Ruff通过。所有正常业务进程按finally停止；schema和SQLite保留，不删除卷或清库。

简历可写：“覆盖6类60次重投、并发及进程中断故障，重复成功退款与资金超额均为0，10次UNKNOWN全部通过原操作查询收敛。”
