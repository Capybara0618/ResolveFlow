# 第三批商品、店铺与账号入口检查

## 商品与店铺资料

Commerce追加V20，PresentationService/Controller及PresentationWire保存商品多图顺序、规格参数、配送/售后说明和店铺简介/头像/电话/营业时间。资料版本与SKU/订单版本分开，图片编辑不更改付款金额或原商品快照。商城卡片通过原两次批量查询同时读取封面，详情可切图；商家上传、排序、移除及预览从“商品管理→图片与详情”进入，店铺资料使用同页独立入口。

Case追加V36 catalog_media登记所属商家，复用AvatarStore图片解码与重编码：头像仍裁剪256方形，商品图片等比缩放至最长边1600；均PNG/JPEG、2MB、原图4096边长以内，移除元数据。文件存现有RESOLVEFLOW_USER_MEDIA_DIR，数据库与媒体目录一起备份。本店未发布图片通过鉴权预览；公开图片必须登记为catalog_media，并由Commerce确认当前挂在已上架商品或启用店铺。任意私有账号avatar_id不能通过公开商品图片接口读取。单商家最多1000个媒体对象，移除展示引用不删除历史文件。

StoreMark在商品、买家订单、咨询列表复用店铺头像；公开店铺资料30秒短缓存并合并同店读取，保存店铺资料后失效。商品旧素材仍作为无上传图片时的默认展示；原订单快照不追改。公开文字说明不修改已发布售后政策或Agent执行权限。

## 注册与找回

Case追加V35 account_recovery。注册只创建平台买家及已有商家绑定，不接受角色/商家身份字段；密码沿用PBKDF2现有实现，8–200位，唯一账号冲突整体事务回滚。注册成功展示一次256位随机恢复密钥，服务端仅存SHA-256哈希，响应no-store、请求/响应record.toString隐藏凭据。

找回需要账号+恢复密钥+新密码；验证通过后旧登录失效，恢复密钥同时轮换，旧密钥不能再次使用。已登录买家可从个人中心→账号安全验证当前密码重新生成密钥。新密钥需用户明确勾选已保存再返回登录；没有恢复密钥时走既有平台管理员重置流程。不模拟发送邮箱或短信。单服务实例内10分钟限制注册10/来源、找回20/来源及5/账号、轮换5/账号；来源采用服务器连接地址，不信任客户端转发头，不宣称分布式限流。

## 实际检查

JDK21 `java/mvnw.cmd -f java/pom.xml -B -pl commerce-service -am -Dtest=PresentationDatabaseTest,ShoppingApiTest,ShoppingDatabaseTest,ShoppingBatchDatabaseTest,CheckoutPaymentDatabaseTest,CheckoutShippingDatabaseTest,PurchaseBatchDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`：36通过，包括封面/资料版本/跨商家拒绝/上下架图片可见、原2语句商品列表与8语句订单列表、付款/收货快照回归。日志tmp/shopping-batch3-commerce-final.log。

JDK21 `java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=EnrollmentApiTest,EnrollmentServiceTest,AccountApiTest,PresentationApiTest,AvatarStoreTest,CommerceShoppingClientTest -Dsurefire.failIfNoSpecifiedTests=false test`：16通过。覆盖正式HTTP注册→登录→恢复→原Token401、拒绝角色注入、密钥轮换/旧密钥拒绝、重复注册回滚、图片比例/跨商家/未发布图片/私有头像隔离。日志tmp/shopping-batch3-case-final.log。测试使用独立MySQL，原项目库未迁移。

`pnpm --dir web test --maxWorkers=2`：42文件314通过；vue-tsc/Vite build通过。商品排序与版本冲突保留输入、图库参数、注册密码一致性和密钥保存确认均有实际组件检查。最后购物售后入口归入完整申请列表，退款筛选与原资金状态区分，最终针对账号/订单/注册四文件24项复验通过，build再次通过，见tmp/shopping-batch3-last-web.log与shopping-batch3-last-build.log。日志tmp/shopping-batch3-web-final.log及shopping-batch3-web-build-final.log。

协议shopping/cart/account/presentation共27通过，新增商品/店铺fixture及严格写请求、注册不可注入角色与找回不可返回登录Token检查。日志tmp/shopping-batch3-contract-tests.log。字段/路径见contracts/core/openapi-presentation.yaml及openapi-account.yaml。

保留失败：首轮前端两个检查引用旧detail-image/shop-store-banner选择器，改为图库/店铺资料组件后原图片规格和店铺断言继续保留，314通过；新增恢复轮换测试时原Session import已被Spotless去除导致编译失败，补回后Case16通过。首轮测试名误写ShoppingServiceDatabaseTest未匹配，后续明确ShoppingDatabaseTest且实际36检查通过，不把未匹配类记为执行。Spotless均定向，不触碰四处原有改动。

## 验收边界

按作者要求，三批先完成代码与自动化，项目服务继续停止，真实页面布局、网关上传、新账号完整购买与售后、真实模型回复和站内提醒接收统一留到之后。未新建项目订单/模型请求、未使用卡皮巴拉演示账号、未恢复拍摄，不将自动化检查称为真实场景验收完成。

提交记录：注册/恢复846c25ba、商品店铺及媒体f5603e20均已正常推送并核实远端；前端与文档随后独立提交。第二批历史JSON兼容2161efb7已推送，最终通知3项复测通过。完整三批进度只记录tasks/todo.md顶部。
