# 展示资料素材

卡皮巴拉头像使用作者于2026-10-29指定的照片，原样保留。助手及三家店铺形象、九张商品补图使用内置 imagegen 生成。生成提示见 assets.json 与 prompts-identity.json；编码后文件尺寸和 SHA-256 记录于 assets.json。

助手形象由公共 UserAvatar 组件统一使用，网页资源为 web/public/identity/v1/assistant.webp。账号头像和店铺、商品资料通过已有鉴权 API 保存，媒体文件由服务端重新编码并持久化。此目录保存可复用的演示素材，不保存登录凭据、上传后的数据库标识或交易资料。

商品保留原主图；耳机、键盘、双肩包复用已有两色图片，其余九款增加一张细节或使用场景图。内容均为演示商品资料，不修改商品价格、SKU、已付款订单快照或退款政策。

## 保存资料

showcase.json 定义三个店铺的简介、营业时间、十二款商品的图集、参数与配送/售后说明。店铺联系入口沿用订单售后咨询，不填写虚构联系电话。商家账号头像与店铺标志使用同一源图。

在已有专用买家 demo_showcase 和三店基础商品的环境中，启动资料服务后执行：

```powershell
agent/.venv/Scripts/python.exe scripts/configure_showcase.py --buyer-credentials tmp/product-film-clean-20261029/credentials.json
agent/.venv/Scripts/python.exe scripts/configure_showcase.py --buyer-credentials tmp/product-film-clean-20261029/credentials.json --apply
agent/.venv/Scripts/python.exe scripts/configure_showcase.py --buyer-credentials tmp/product-film-clean-20261029/credentials.json --verify
```

凭据文件只包含 username/password，不提交。脚本默认预览，仅连接既有8180网关；正式商家接口按所属店铺上传并保存，版本冲突停止。已有其他内容不会被自动覆盖。上传和保存记录位于忽略目录 tmp/showcase-config/journal.json，用于断点接续和跳过已保存图片；该文件不是可迁移数据库备份，媒体目录与业务库仍需共同保留。脚本不会创建账号、订单或咨询。

## 商品评价展示

`reviews.json` 保存无线降噪耳机的3条展示评价文案：5星黑色、4星银色、5星黑色，其中2条有商家回复。这些是功能与拍摄样例，非商用客户证言。网页按现有规则公开显示“已购用户”，不公开买家账号资料。

2026-10-30已通过正式API完成3笔新订单的付款、商家发货、受控物流DELIVERED、买家发表及商家回复；卡皮巴拉只增加一笔正常签收订单，其余两笔归专用背景账号。原退款展示订单及其他账号的订单/评价保留。没有直接插入评价或绕过已签收资格。

执行日志、订单标识和冻结幂等键保存在忽略目录 `tmp/buyer-reviews-20261030/journal.json`，凭据不提交。此目录仅保存展示文案，不将数据库标识或凭据作为可迁移fixture。另一个环境可按购物→付款→商家发货→已有物流模拟器DELIVERED→订单评价→商家商品评价回复的流程准备，具体界面操作见 录制指南（本地开发记录）。商品页评分与列表使用正式查询，未设置网页固定分数或伪造的前端评价。
