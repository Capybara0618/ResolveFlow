# 物流场景模拟器：开发计划与操作约定

2026-10-14。用户已授权先实现物流场景模拟器，供后续客服演示与评测推进物流事实。使用现有Commerce模拟物流与数据库，不接真实承运商，不增加新微服务或商家物流编辑页面。实际完成状态与命令仅维护在 [todo顶部](../tasks/todo.md)。

## 场景与入口

第一版为本地Python命令行工具，沿用项目锁定环境和现有Docker/MySQL客户端，无新增Python依赖。只操作已核验所属本地演示Compose项目的commerce_db；测试使用隔离MySQL。

按订单推进，该订单全部商品行处于同一模拟物流场景；若评测需要同一多行订单的不同物流，另行细化，当前不承诺拆包裹。必须先通过既有商家接口首次发货，模拟器不代替付款/首次发货。

| 操作 | 物流事实 |
| --- | --- |
| IN_TRANSIT | 追加运输节点，当前仍在途 |
| DELAYED | 追加异常延迟记录，结论仍IN_TRANSIT，不代表已丢失 |
| DELIVERED | 追加签收事件及DELIVERED结论 |
| LOST | 追加模拟承运商丢失事件及LOST结论 |
| UNKNOWN | 追加承运商状态不明确事件，保留此前历史 |
| UNAVAILABLE / AVAILABLE | 开启/恢复本订单物流查询503故障，不改物流事实/版本/事件 |
| inspect | 读取订单/行物流、事件、故障状态，供评测记录 |

签收争议由DELIVERED数据与客户“未收到”陈述构成，不增加伪争议状态。长时间无更新应保留旧事件：可inspect指定评测观察时间计算距最后更新时长，但这个观察时间不会自动改变Agent/服务时钟；刚发货订单不能倒改旧时间，后续实测需自然等待或独立准备时间合理的样本。

## 状态与一致性

只推进已模拟发货的checkout订单，验证商家与订单归属、预期履约版本和当前所有行。DELIVERED/LOST为终局，不能用模拟器倒退或互换；对照实验用独立样本。物流与资金独立，模拟器不修改退款占用、授权、金额、Case输入或旧调用记录。

追加迁移放宽V14履约约束，使已发货的后续状态/version有效；不修改已执行迁移。单事务更新全部行shipment、追加shipment_event、更新order_fulfillment及请求收据。锁序沿用payment_ledger→order_fulfillment→按line_id顺序shipment；相同请求键/载荷重试返回原收据，不重复追加；换载荷同键拒绝，旧版本拒绝。事件数量不超过现有读取上限200，避免最新事实被旧分页截断。

故障记录在独立表中，通过现有Java物流读取服务返回503；已有工具HTTP错误处理继续沿用。查询故障不冒充UNKNOWN结论。开启/恢复使用请求键并与订单锁协调，不开放HTTP写入口或Agent写工具。

## 实施小步

1. 本计划/范围与进度记录，差异/链接核查后独立提交推送。
2. 先写真实MySQL关键失败测试；追加迁移与事务过程、本地命令行、Java故障读取，实现上述完整能力。过程在DB中供本地脚本CALL，不由正常用户/模型调用。
3. 集中验证迁移、场景/终局、重复请求/并发、错商家/旧版本、回滚/保留历史、多行一致、故障503恢复及资金不变；复用发货/物流读取回归。编译/格式/CLI检查，报告失败与未运行。
4. 文档补使用示例及报告，按已授权精确提交推送。验证不启动真实模型、清库/删卷或重写旧实验；不会为演示自动消费已有待调查工单。

## 使用方式

实现与真实MySQL验证见[验证报告](../reports/logistics-simulator/README.md)。使用前Commerce必须通过正常Flyway启动应用V16；Java更新后重新构建/启动才加载故障处理。本轮没有启动日常业务栈或对现有订单写入场景；缺少V16时工具会返回SQL错误，而不是假成功。

先正常购物、模拟付款，并由对应商家首次模拟发货。复制该商家订单ID，以下占位值需换成实际ID。使用项目现有Python环境，从仓库根目录执行：

```powershell
# 只读检查，找到当前fulfillment_version
.\agent\.venv\Scripts\python.exe scripts/logistics_simulator.py inspect --merchant-id M-1001 --order-id <订单ID>

# 以首次发货后的version=2为例，追加签收事件
.\agent\.venv\Scripts\python.exe scripts/logistics_simulator.py advance --merchant-id M-1001 --order-id <订单ID> --expected-version 2 --scenario DELIVERED --request-key eval-signed-001
```

返回`receipt`是这次请求的原始持久收据，`current`是随后读取的当前物流。重试使用完全相同的key、version和参数；成功后新操作使用新的key及最新version。以后有新进展再重放旧请求时，原收据和当前快照可以不同，旧请求不会回退状态。

可将场景替换为`IN_TRANSIT`、`DELAYED`、`LOST`或`UNKNOWN`。DELIVERED/LOST不能再转其他物流结论；不同终局对照用不同订单。一次操作影响整单全部行，事件/version及履约投影同事务更新；历史事件及金额保持。

```powershell
# 查询故障开关不增加履约或物流事实版本；以下2需换成当前版本
.\agent\.venv\Scripts\python.exe scripts/logistics_simulator.py advance --merchant-id M-1001 --order-id <订单ID> --expected-version 2 --scenario UNAVAILABLE --request-key fault-on-001
.\agent\.venv\Scripts\python.exe scripts/logistics_simulator.py advance --merchant-id M-1001 --order-id <订单ID> --expected-version 2 --scenario AVAILABLE --request-key fault-off-001
```

故障影响Java私有物流查询（Agent实际读取的路径），不会把失败改装成UNKNOWN；订单/商家工作台仍可读取已保存的履约投影。数据库可保存开关，但旧Java进程不会自动加载新处理逻辑，必须更新服务；关闭开关是明确的AVAILABLE操作。

`--occurred-at`可指定带时区的事件时间，要求不早于现有最后事件且不在未来。不填时使用数据库UTC时间，并为与应用发货时钟不超过1秒的偏差对齐到最后事件时间；更大未来偏差明确拒绝。不会倒改ORDER_PAID或SIMULATED_SHIPPED时间。

`DELAYED`代表承运商报告异常延迟，仍是IN_TRANSIT。它会追加一个当前异常事件，不能因此宣称已构造“七天没更新”。`inspect --observed-at <带时区时间>`仅计算评测参考时间距最后事件多久，输出明确标记未更改服务时钟；真实Agent的时间判断仍需自然等待或时间合理的独立fixture。本版不实现全系统虚拟时钟/历史重置。

首次发货仍走原商家接口；旧种子只读物流不由本工具改写。脚本只连接校验过Compose归属的本地演示MySQL，不提供远程数据库参数。普通用户和Agent不获得此写入口；无需模型API密钥即可运行模拟器本身。
