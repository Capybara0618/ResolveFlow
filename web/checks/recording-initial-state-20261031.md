# 拍摄初始状态准备与核验（2026-10-31）

用户要求宣传片使用干净、纯粹的账号状态；确认保留3条评价，商家仅有3笔已完成背景订单，前景买家、咨询、售后与消息为空。本批已经切换到独立拍摄数据，不在旧验收库删除订单或隐藏列表记录。

## 已完成状态

| 入口 | 实际初始状态 |
| --- | --- |
| 买家display01／卡皮巴拉 | 头像、昵称、默认地址保留；本人购物车商品0、订单0、咨询0、售后0、消息0 |
| 商家admin01／松间数码 | 交易仅3笔已签收背景订单；售后工单0、咨询核查0、消息0，概览无待处理事务 |
| 商品 | 三家店铺、12款在售精选商品，原图集/规格/介绍/店铺图片保留；耳机评价3条，评分4.7，回复2条 |
| 平台platform | 三家店铺、所选账号与3个背景买家；客服运行记录0 |
| Agent与退款 | 支持真实orchestrated-v1调查，精确政策索引复用；本次模型调用0，退款执行0，无假造调查轨迹 |

本次背景买家为record_review_01、02、03，均为独立拍摄身份。每人通过正式注册、地址、草稿、模拟付款、商家发货、受控签收、本人评价和商家回复入口生成1笔订单。没有把卡皮巴拉历史订单改成别人的订单，没有SQL插入孤立评价。付款合计100700分，对应329/349/329元三个样例，无退款或预留。

卡皮巴拉的旧两笔订单、其他验收账号/工单与运行记录仍在原resolveflow-review-demo数据卷；拍摄环境不读取它们。后台也未加隐藏历史或只显示拍摄记录的筛选特例。

## 实现与隔离边界

- `infra/compose.recording.yaml`复用现有锁定服务定义，固定项目resolveflow-recording-v1。合并配置核实MySQL/PG卷分别为resolveflow-recording-v1_demo-mysql-data与resolveflow-recording-v1_demo-postgres-data，非external卷；Redis、RocketMQ亦为独立容器/存储。
- `scripts/recording_stage.py`停所属应用后，只读复制全表结构/Flyway、目录/政策、所选身份/默认地址、受限图片和精确政策索引。交易、咨询、工单、Outbox、调用账不复制。原卷保持，未执行reset/TRUNCATE/DROP/down -v。
- 拍摄媒体与provider文件位于独立tmp/recording-stage-v1目录；身份版本递增，使旧页面登录需要重新认证。复制未创建新业务授权。
- `scripts/project_runtime.py`识别固定选择标记tmp/active-recording-stage.json；普通start/status/stop保留所选数据。拍摄启动绕过历史场景witness/backfill路径，仅启动现有服务与真实Agent，不依赖更早共享环境。
- `scripts/logistics_simulator.py`跟随相同选择，拍摄第三段的LOST准备不会误写旧验收订单。
- `scripts/recording_reviews.py`只在明确拍摄项目与已完成导入标记下运行；幂等键/载荷在写前保存，重复准备沿用同一3笔订单和评价。不在开拍后的正常启动中自动重新生成或清零。
- 提供select-original/select-recording保留两套数据切换。初始化目录已有时拒绝覆盖，导入未完成禁止普通启动；切换停止失败保留当前选择。两套环境共用端口，轮流运行，不并行抢占。

原数据/私有凭据/恢复密钥/SQL结构与资料副本均留忽略tmp，不提交。背景密码随机，未输出或写入公共报告；仓库仅包含用户指定的演示口令说明。

## 实际命令与结果

| 命令 | 结果 |
| --- | --- |
| `python -m pytest agent/tests/unit/test_recording_stage.py -q`（接入前） | 1失败5通过，证实普通启动尚不跟随拍摄选择；保留first-tests日志 |
| `docker compose -f infra/compose.recording.yaml config --format json` | 固定项目/端口与独立命名卷核实通过 |
| `python scripts/recording_stage.py prepare` | 独立库/图片/政策索引复制完成，原卷停用并保留 |
| `.\start.ps1 -SkipBuild -NoBrowser` | 首次被历史shared-witness要求阻塞，已调整拍摄分支；最终完整10项健康通过 |
| `python scripts/recording_reviews.py` | 3笔后台订单均签收，3评价/2回复，前景买家与两端事务入口为空 |
| `python scripts/recording_stage.py verify-original` | 仅启原数据库只读核对；原Case、Commerce、Agent完整数据dump摘要均与准备前一致，再停原库并恢复拍摄依赖 |
| `.\start.ps1 -SkipBuild -NoBrowser`后`python scripts/recording_reviews.py --verify` | 重启后全部初始状态不变，原精确索引复用，模型调用仍0 |
| 再次`python scripts/recording_reviews.py` | 同一3个背景订单/评价，不增加数量；最终仍3条、4.7分、2回复 |
| `python -m pytest agent/tests/unit/test_recording_stage.py agent/tests/unit/test_project_runtime.py agent/tests/unit/test_reviewer_demo_driver.py scripts/test_logistics_simulator.py -q` | 最终62项通过，含固定选择/初始化拒绝覆盖/部分导入拒绝/原环境拒绝评价写入/切换失败保留标记/物流跟随选择与旧生命周期回归 |
| 12商品资料/24张商品图/3店标志正式网关读取 | 24张图片逐字节匹配独立媒体文件；规格/配送/售后/店铺介绍均存在 |
| `ruff check`（本批脚本与测试） | 最终通过；最初长行/导入顺序/check参数提示已修正 |
| `git diff --check`（本批文件） | 通过；未重建Java、未改Vue/CSS，因此未重复整站构建或模型质量评测 |

实际命令使用agent/.venv/Scripts/python.exe。中间一次pytest误列不存在的agent/tests/unit/test_logistics_simulator.py，未运行测试；改为真实scripts/test_logistics_simulator.py后最终62项通过。另一轮旧生命周期测试受真实选择标记影响，补隔离夹具后通过，未删业务断言。

日志：tmp/recording-stage-{prepare,start,start-final,restart,tests,tests-final,regression,verify-after-restart,repeat}.log，tmp/recording-reviews-prepare.log，tmp/recording-source-integrity.log。可审查摘要：tmp/recording-stage-v1/verified-initial-state.json、source-integrity.json、media-verification.json；原文与凭据不公开。

## 网页与剩余边界

准备阶段通过正式网关API核对三角色及图片/空列表/订单/评价；当时浏览器访问关闭，未称页面验收通过。用户重启后，本日已补齐下述三端实机验收，本批未修改页面样式。

原验收5个基础容器当前均exited且卷保留；拍摄5个基础容器及三个Java、Agent、前端运行。同一入口http://127.0.0.1:5174/#/shop，用户刷新重新登录display01即可从新状态拍摄。不要为了检查聊天而预先发送消息，以免把正式起点变成已有会话；正式第一条咨询即为本轮真实模型操作。原四历史脏文件保持。

## 重启后的三端网页验收

2026-10-31，用户恢复浏览器访问后，首次status显示基础设施健康、五项应用服务停止。执行`.\start.ps1 -SkipBuild -NoBrowser`沿用拍摄选择与数据，最终退出0、10项健康全部通过、政策索引原版本复用。网页启动前两次访问连接拒绝是服务尚未就绪，恢复后新页正常；未借此重置环境。

在1280×720浏览器窗口分别用display01、admin01、platform真实登录并点击页面：

| 页面 | 实机结果 |
| --- | --- |
| 买家商城 | 卡皮巴拉照片与昵称正确，商品图片和店铺入口正常 |
| 我的订单／我的售后／购物车 | 三类列表为空 |
| 售后咨询 | 没有咨询记录；订单选择器提示暂无已付款订单，关闭后回到咨询初始画面 |
| 买家消息 | 展开后“暂时没有消息”，无未读数 |
| 耳机详情 | 3条评价、4.7分、2条商家回复均在DOM；评价入口可定位到展示区 |
| 耳机规格 | 银色349元对应第2张图片，切回黑色329元对应第1张图片，媒体URL不同；未点击购买或加入购物车 |
| 商家概览 | 三项待办为0，无待发货订单、待回复咨询或待核实售后 |
| 商家交易订单 | 仅3笔已签收背景订单，金额329／349／329元，无退款，下一页禁用 |
| 商家售后工单／咨询核查／消息 | 均为空，工单与核查计数为0 |
| 平台客服运行记录 | 暂无运行记录，无旧调查轨迹 |

三端当前页面均无图片加载失败，document.scrollWidth=1265小于窗口1280，无横向溢出；三端warn/error日志均为空。网页截图和DOM读取只用于核对真实界面，未注入页面状态。规格初次使用AX给出的checkbox角色定位失败，读取真实DOM后改用button定位通过，非商品功能失败。

截图在`tmp/recording-stage-v1/browser-acceptance-20261031/`：buyer-shop、buyer-orders-empty、buyer-aftersale-empty、buyer-support-empty、buyer-cart-empty、buyer-messages-empty、product-reviews、product-silver、merchant-overview、merchant-orders-three、merchant-aftersale-empty、merchant-support-empty、merchant-messages-empty、platform-runs-empty（PNG）；布局与控制台摘要为page-checks.json。评价窗口截图显示评分与前两条，第三条及两回复由完整DOM确认，未把截图外内容称为同屏可见。

网页验收前后分别执行`python scripts/recording_reviews.py --verify`均通过：前景订单／购物车／咨询／售后／消息仍0，商家仅3背景签收订单，评价3／回复2／4.7分，模型调用与退款仍0。本轮不新增订单或试聊，不重复收费模型质量评测，不重新运行上批62项代码回归；本轮只有启动、只读页面/API检查与报告更新。

收尾保留已登录的买家商城与商家概览供用户录制，关闭临时平台页，未设置视口覆盖。拍摄初始状态的API与三端页面核对均已完成，正式录制按README.recording-guide.md从第一段开始。
