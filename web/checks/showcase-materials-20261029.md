# 展示资料配置检查

## 统一形象与素材

2026-10-29：作者指定水豚照片用作 demo_showcase（卡皮巴拉）头像。内置 imagegen 生成客服小助手、三店标志和九款商品补图，逐张核对参考商品的颜色、形状和主要结构；三款多色商品复用现有各色主图。素材与哈希见 fixtures/showcase/v1/assets.json，提示见同目录 prompts-identity.json。未采用先前生成的水豚插画。

公共 UserAvatar 接入 assistant.webp，历史消息、生成中消息、欢迎区及会话标题共用同一图片；加载失败保留原品牌 SVG。账号和商家头像继续使用受鉴权保护的账号资料，不将指定水豚照片设为所有买家的默认头像。

实际命令：pnpm --dir web test --maxWorkers=2 tests/account-workspace.spec.ts tests/support-workspace.spec.ts tests/shopping-presentation.spec.ts：3文件40项通过；pnpm --dir web build：vue-tsc/Vite通过。初次模板静态根路径被Windows/Vite测试转换为file:///identity地址，导致2套件无法加载；改为绑定共享资源路径后上述40项复测通过。首次命令误写product-presentation.spec.ts（不存在），最终命令修正为shopping-presentation.spec.ts，未将缺失文件计为通过。

Java当前源码使用JDK21执行 java/mvnw.cmd -f java/pom.xml -B -pl case-service,commerce-service,gateway -am -DskipTests package 构建通过。本次仅为素材配置启动MySQL/Redis与三Java进程，消息消费、退款、结算恢复和Agent调查关闭；没有执行统一下单/售后真实验收。

## 正式资料配置与读回

通过 scripts/configure_showcase.py 默认预览、--apply 保存、--verify 只读核对。既有网关8180与商家/账号正式API实际完成：demo_showcase指定照片头像，admin01/02/03与对应店铺同源标志，三店简介和营业时间，十二款精选商品各两张图、参数、配送与售后说明。店铺使用已有订单咨询联系入口，未填写虚构电话号码。商家上传公开媒体共27个；四个账号头像按私有账号接口单独上传，不混用公开媒体标识。

所有头像读回均为服务端256×256 PNG。公开三店资料、十二款商品资料与保存结果逐字段一致，24张公开图片可读取，各商品cover_image_id与图集首图一致。随后再次--apply，媒体计数、头像及资料版本和整个记录文件均未增加/改变。关闭所属进程及依赖，再启动同一资料服务，--verify再次通过，文件和资料持久化成立。Case V33–V36与Commerce V19–V20在原资料库实际迁移成功；服务启动时关闭消息消费、发布、退款派发/对账、结算恢复与Agent调查。

前后对orders、order_line、payment_ledger、refund_operation、checkout_draft、checkout_draft_line、aftersale_case、case_authorization做CHECKSUM TABLE比对一致；商品身份/名称/原asset_key/version与SKU规格/价格/version逐项一致。demo_showcase真实登录GET /api/v1/orders和/support/conversations前后均为空，无新订单、咨询、退款、模型请求或录制。实际记录与凭据均留忽略目录tmp/showcase-config和原专用账号凭据文件，不提交。

新增 agent/tests/unit/test_configure_showcase.py 最终6项通过，覆盖已有资料拒绝覆盖、接续版本与内容匹配、仅初始化空资料、路径不能越界、响应不确定时仅接纳正确版本与内容；ruff check通过，ruff format后6项复测通过。早期脚本尚未创建时临时探针收集失败，该日志保留，不将其作为有效行为失败测试证据。最终源审发现头像在预检后重新读取版本可能接纳并覆盖并行资料修改；新增并发回归先失败（8与7不符），改用预检时的版本交给正式API校验后6项全过。素材与实际配置脚本分两个小步提交，首步6fc56e2d已正常推送。

本轮验证范围为资料上传、保存、公开读取、重复执行和重启持久化；尚未执行三批购物/客服/退款的完整真实场景或浏览器布局验收。收尾再次stop.ps1并核对所属进程和容器停止，保持拍摄暂停。
