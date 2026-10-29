# 第一批购物基础功能验证

## 资料与地址后端

新增Case迁移V33、AccountService/Controller、AvatarStore。本人资料编辑、PNG/JPEG头像上传/鉴权读取、买家地址增改删和默认地址均持久化。昵称更新不改变登录身份版本；写入锁住当前有效账号，地址变更在同一买家锁下串行化。头像重新编码为256×256 PNG，上传上限2MB，原图长宽上限4096。

实际验证：JDK21下运行`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=AvatarStoreTest,AccountServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`，7项通过，0失败、0跳过。数据库测试使用Testcontainers独立MySQL，原项目服务/数据卷未启动或修改。定向Spotless通过。

失败记录：首次使用系统JDK17被版本门禁拒绝，改用已安装JDK21；测试夹具先漏platform_buyer外键，再漏identity_version=1，修正夹具后通过；首版Spotless误用glob、第二次正则含管道经cmd解释失败，改为无管道正则列表后通过。最先的头像测试与实现编译有时间重叠，未声称获得有效的先红证据。

## 尚在实施

个人资料/地址前端已接线并通过一次build，后续聊天头像、结算地址和订单快照仍需集中验证。当前不称第一批完成，不启动拍摄或真实模型。原始日志保存在忽略目录tmp/shopping-basics-*。

## 结算与固定收货信息

2026-10-29追加Commerce V19 checkout_shipping：草稿和收货快照同事务，付款创建订单并关联原草稿。立即购买和购物车统一携带地址ID/版本，Case校验本人地址后发送可信快照；Commerce重试先读取原草稿，不要求再次读取已修改或已删除地址。相同幂等键不能换地址版本或内容；买家和本店商家按订单归属读取，旧订单明确返回空快照。原Agent订单和物流投影不增加地址电话。

JDK21实际运行`java/mvnw.cmd -f java/pom.xml -B -pl case-service,commerce-service,gateway -am -Dtest=AccountServiceTest,AvatarStoreTest,AccountApiTest,ShopApiTest,SupportApiTest,CartBuyerApiTest,CheckoutBuyerApiTest,CommerceShoppingClientTest,CheckoutShippingDatabaseTest,CheckoutPaymentDatabaseTest,MultiCheckoutDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false package`：Commerce 28项通过（3收货快照、14付款、11多行结算），Case部分检查通过但整条命令失败，原因见下。Gateway本次仅构建，未执行Gateway测试。日志tmp/shopping-basics-final-java.log。

Case同轮AccountServiceTest5、AvatarStoreTest3、CartBuyerApiTest5、CheckoutBuyerApiTest4、CommerceShoppingClientTest7、ShopApiTest4通过；头像HTTP夹具撞buyer唯一约束，聊天身份越权拒绝错误映射500，修正后针对AccountApiTest/SupportApiTest复测33项全部通过（头像HTTP1、咨询接口32），日志tmp/shopping-basics-case-retest.log。Case共61个不同检查分组已通过，重叠不累加；保留整轮失败。

协议`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_shopping.py agent/tests/unit/test_contracts_cart_checkout.py -q`：19通过。初版ShippingSelection错误追加在根security列表中，导致引用不可解析，移动至components.schemas后复测通过；Case/Commerce保持同一请求Schema。新迁移外键字符集在执行前已按原checkout_draft对齐，实际Testcontainers迁移V19成功。

## 前端检查与验证顺序

`pnpm --dir web test --maxWorkers=2`：40文件306项通过；最终补齐匿名评价默认头像、本人评价头像和商家本人消息方向后，`pnpm --dir web test --maxWorkers=2 tests/account-workspace.spec.ts tests/cart-workspace.spec.ts tests/marketplace.spec.ts tests/support-workspace.spec.ts tests/product-reviews.spec.ts tests/product-review-editor.spec.ts`六文件70项通过。各组重叠不累加。vue-tsc/Vite build通过，后续最终构建结果按收尾追加。

首次默认并发全量Vitest启动过多worker，8文件45项通过但31个worker启动超时，不能记为全绿；改maxWorkers=2后完整306通过。用户重启应用曾终止第二轮Case测试/临时容器，未完成日志不计为通过。旧结算API测试未携带地址曾400，更新为正式地址簿创建和可信地址选择后ShopApiTest4通过。

浏览器访问已恢复，但作者最新要求三批代码与自动化完成后统一启动真实场景验证。曾仅为验收启动项目五依赖，随后stop.ps1正常停止，三个Java、网页与Agent均未启动；新业务订单、模型请求、拍摄均0。独立测试容器不属于项目运行环境。真实页面及新订单端到端验收待三批完成后进行。

## 第一批代码收尾

头像HTTP/聊天身份33项复测通过，首轮Case其余28项保持通过，合计61个不同Java检查；Commerce28项通过。最终`pnpm --dir web build`通过（151模块），最后一次欢迎区品牌头像替换为同一UserAvatar，未新增行为。全量306和最后六组70为重叠验证，不累加。前端新增四项资料/地址组件检查、两个无地址禁止下单检查；数据库新增收货快照与本人地址版本/归属检查。

第一批代码包括个人资料入口、昵称/图片头像、买家与商家/助手消息作者身份、默认图失败回退、地址新增编辑删除默认、结算地址选择、买家和商家收货快照。公开评价保留匿名默认图，本人评价编辑显示本人头像；不新增公开账号信息查询。

后端结算独立提交fad37c5e已正常推送并核实远端。完整第一批代码提交与下一批进度仅记录于tasks/todo.md顶部；三批统一真实场景验证尚未执行，拍摄未恢复。原docs/engineering.md、RefundAcceptanceApiTest、scripts/verify.ps1与verify.sh四处旧改动保持，未夹带。
