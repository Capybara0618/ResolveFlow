# 第二批购物体验检查

## 站内消息

新增V34本人已读状态、NotificationService/Controller。提醒投影自已提交的商家回复、买家给商家的补充、核查单及工单关键事件；消息不拷贝私聊正文/内部轨迹，商家不能读取买家与助手私聊。本人读取与标为已读均按当前身份和归属；source ID稳定，反复刷新不生成重复通知，已读更新幂等。历史核查单created_at保留NULL，不伪造创建时刻。

`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=NotificationServiceTest,SupportApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：34通过。最后追加退款结果与补材料投影检查、当前binding匹配与索引，针对NotificationServiceTest复验结果收尾追加。数据库为独立Testcontainers。

## 订单购物阶段与个人入口

付款状态保持原协议；新增可选shopping_stage，按账本退款/预留、订单行物流快照判断待发货、待收货、已完成、售后、物流待确认。新阶段筛选在Commerce分页候选SQL完成，不能只过滤当前前端一页；Case跨店合并保留原cursor身份与筛选绑定。未到资金预留的售后申请继续从“售后申请”入口查看，本批不新增确认收货或改变评价/退款权限。

首轮PurchaseBatchDatabaseTest发现额外一次查询使原8语句上限失败；合并阶段读取到原批量账本SQL后，6项分页/并发一致性/实际执行计划检查与4项收货/阶段数据库检查通过。没有放宽原断言。Case CheckoutBuyerApiTest4/CommerceShoppingClientTest7/NotificationServiceTest2共13项及已有其他实际命令见tmp/shopping-batch2-final-java.log（完整结果收尾补记）。

前端增加买家/商家消息入口、精确会话或工单跳转、个人中心、购物阶段入口；保留原筛选返回订单列表、原商品登录返回和结算内地址管理。`pnpm --dir web test --maxWorkers=2`：41文件310项通过；此前针对4文件65通过，与全量重叠不累加。vue-tsc/Vite build通过。协议shopping/cart/account23通过。

失败记录：首轮模板直接使用URLSearchParams触发vue-tsc不可见全局，改script计算属性；阶段候选SQL别名改变导致原注入时点未命中，恢复原SELECT id前缀并保持一致性检查；首次协议字段插入位置误命中dependentSchemas，YAML解析先报错，修正为精确同级properties后23通过。所有原日志保留tmp/shopping-batch2-*。

三批代码完成后统一真实场景验收，当前未启动项目服务、未新模型/订单/录制，不能以自动化结果宣称实机完成。
