# D1.1：交易竞争基础预检

2026-10-26，沿用[D0隔离环境](README.md)的真实Gateway/Case/Commerce和冻结的优化前JAR。新增[evaluation/backend_trade.py](../../scripts/evaluation/backend_trade.py)及5项计分/续接检查，覆盖T01/T02/T04/T05。此处是开发预检，尚未完成[正式协议](../../docs/backend-resume-evaluation-v1.md)的8类160轮，也不回填简历数字。

## 实际结果

四类各10/30两个并发档，各1轮，共8轮、160个竞争POST请求；登录、准备、核验和T02追加冲突确认单列，未混入160分母。实际结果如下：

| 场景 | 10并发 | 30并发 | 核对 |
| --- | --- | --- | --- |
| T01 同购物车同revision修改 | 1成功/9冲突 | 1成功/29冲突 | revision仅加1，保存数量对应唯一成功请求 |
| T02 同多行结算key、两种内容 | 5原内容成功重放/5冲突 | 15原内容成功重放/15冲突 | 同key唯一草稿，原内容同ID，不同数量409 |
| T04 同草稿同付款key | 10成功重放 | 30成功重放 | 每轮一个attempt/成功收据/订单，两行与两个退款槽完整 |
| T05 同草稿不同付款key | 1成功/9冲突 | 1成功/29冲突 | 每轮只有一个付款业务结果，其他key未产生多余成功收据/订单 |

合计64个200、96个预期409、意外错误0。付款涉及4个独立业务组/4个订单/4份成功收据，每单两行共52800分；行金额之和、草稿金额、收据与支付账本一致，预留/退款为0。没有把160请求称为160笔付款。

原始请求输入、响应/实际耗时、结果和[审计](c5265fe48bc946ec99398450c998a014/trade-probes/d1-preflight-01/audit.json)均保留。第一份[summary.json](c5265fe48bc946ec99398450c998a014/trade-probes/d1-preflight-01/summary.json)停在4个已核验轮；修复运行器后[summary-resumed.json](c5265fe48bc946ec99398450c998a014/trade-probes/d1-preflight-01/summary-resumed.json)完成8轮，并保存修复前文件hash，旧文件逐字不变。

## 中断与失败保留

首次T04-c10请求已完成、请求记录已保存，但payment_counts的JSON_OBJECT汇总SQL少一个右括号，MySQL1064使核对中断。原因在新运行器，不在交易服务。修正后只读原已保存请求与账本，未重发T04-c10付款；其余3个尚未执行付款轮随后正常完成。新增续接测试先失败（实现仍试图创建新购物车/草稿），实现读取prepared/requests后通过。

运行器预先写prepared和发送开始标记，完整请求结果落盘后可继续核对；若只有发送开始而无完整结果，明确拒绝盲目重发，要求按原key/资源核查。已完成结果保留，修复后结果另名存储；正式矩阵仍需更完整的逐请求即时记录和场景门控，不能用本预检替代正式执行器。

计分原4项先缺模块失败后通过，续接新增1项先失败后通过；最终`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_backend_trade_probe.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q`共43通过、1旧弃用警告，4.69秒。新脚本与新测试Ruff通过；无生产代码修改，无新增模型请求/费用。

## 实际命令

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-preflight-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_trade.py --run-id c5265fe48bc946ec99398450c998a014 --probe-id d1-preflight-01 --resume
```

第一条已存在输出不能覆盖。第二条用于本次尚未完成轮的续接，原summary和请求保持，另写resumed汇总；不要对已完成正式数据反复重跑追分。运行状态、provider SQLite和进程日志仍在忽略tmp，数据容器/卷保留。

T03结算与商品更新、T06公共响应丢失、T07收据后真实崩溃、T08到期竞争仍待独立门控/反例；本次结果仅支持表中四类正常竞争。后续D2授权退款矩阵、D3查询批量化及D4 Redisson/正式性能矩阵未执行。

本轮收尾实际核对10端口全部关闭，数据/容器/Broker卷保留，退出记录见[stopped.json](c5265fe48bc946ec99398450c998a014/stopped.json)。无原业务进程或费用操作。
