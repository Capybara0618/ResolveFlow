# 展示资料配置检查

## 统一形象与素材

2026-10-29：作者指定水豚照片用作 demo_showcase（卡皮巴拉）头像。内置 imagegen 生成客服小助手、三店标志和九款商品补图，逐张核对参考商品的颜色、形状和主要结构；三款多色商品复用现有各色主图。素材与哈希见 fixtures/showcase/v1/assets.json，提示见同目录 prompts-identity.json。未采用先前生成的水豚插画。

公共 UserAvatar 接入 assistant.webp，历史消息、生成中消息、欢迎区及会话标题共用同一图片；加载失败保留原品牌 SVG。账号和商家头像继续使用受鉴权保护的账号资料，不将指定水豚照片设为所有买家的默认头像。

实际命令：pnpm --dir web test --maxWorkers=2 tests/account-workspace.spec.ts tests/support-workspace.spec.ts tests/shopping-presentation.spec.ts：3文件40项通过；pnpm --dir web build：vue-tsc/Vite通过。初次模板静态根路径被Windows/Vite测试转换为file:///identity地址，导致2套件无法加载；改为绑定共享资源路径后上述40项复测通过。首次命令误写product-presentation.spec.ts（不存在），最终命令修正为shopping-presentation.spec.ts，未将缺失文件计为通过。

Java当前源码使用JDK21执行 java/mvnw.cmd -f java/pom.xml -B -pl case-service,commerce-service,gateway -am -DskipTests package 构建通过。本次仅为素材配置启动MySQL/Redis与三Java进程，消息消费、退款、结算恢复和Agent调查关闭；没有执行统一下单/售后真实验收。

账号、店铺与商品实际保存及读回结果在后续配置小步追加。
