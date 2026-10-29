# 第一批购物基础功能验证

## 资料与地址后端

新增Case迁移V33、AccountService/Controller、AvatarStore。本人资料编辑、PNG/JPEG头像上传/鉴权读取、买家地址增改删和默认地址均持久化。昵称更新不改变登录身份版本；写入锁住当前有效账号，地址变更在同一买家锁下串行化。头像重新编码为256×256 PNG，上传上限2MB，原图长宽上限4096。

实际验证：JDK21下运行`java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=AvatarStoreTest,AccountServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`，7项通过，0失败、0跳过。数据库测试使用Testcontainers独立MySQL，原项目服务/数据卷未启动或修改。定向Spotless通过。

失败记录：首次使用系统JDK17被版本门禁拒绝，改用已安装JDK21；测试夹具先漏platform_buyer外键，再漏identity_version=1，修正夹具后通过；首版Spotless误用glob、第二次正则含管道经cmd解释失败，改为无管道正则列表后通过。最先的头像测试与实现编译有时间重叠，未声称获得有效的先红证据。

## 尚在实施

个人资料/地址前端已接线并通过一次build，后续聊天头像、结算地址和订单快照仍需集中验证。当前不称第一批完成，不启动拍摄或真实模型。原始日志保存在忽略目录tmp/shopping-basics-*。
