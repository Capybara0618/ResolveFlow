# 专用演示账号准备

2026-10-29，按作者要求将产品影片改为专用买家账号拍摄。

## 已完成

- 通过正式平台买家管理API创建`demo_showcase`，显示名“林然”，账号启用。
- 使用该账号正常登录，读取`GET /api/v1/orders`和`GET /api/v1/support/conversations`，两者`items`数量均为0。
- 更新拍摄方案：只拍一笔新订单、一段咨询和对应退款；商家筛选该订单，平台展开对应运行详情。
- buyer10前一轮试拍及原有测试数据保留。

实际命令为`agent/.venv/Scripts/python.exe tmp/prepare_clean_film.py`；检查回执保存在忽略目录`tmp/product-film-clean-20261029/account-readiness.json`。账号凭据单独保存在忽略目录，未写入报告和提交。

## 当前未完成

浏览器工具返回“Local browser use is disabled in Work settings”，当前无法登录页面重拍。已请求作者开启“本地浏览器访问”。本次只创建账号并核对空记录，未创建新订单或调用模型，未交付正式视频、动图和新截图。

恢复后先核对实际画幅和完整入镜，再用专用账号拍摄购买、咨询、买家确认、商家核验审批及结果。视频与动图继续按拍摄方案制作，并在交付前核对金额、同单身份、实际调用和素材可读性。
