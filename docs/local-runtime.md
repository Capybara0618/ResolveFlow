# 本机运行

完整商城入口支持Windows PowerShell。需要Docker Desktop（Linux containers）、JDK21、Python3.12、uv、Node22和pnpm12.4.1，版本以Maven/uv/pnpm锁为准。

## 安装依赖

项目根目录执行：

```powershell
uv sync --project agent --frozen --all-extras
pnpm --dir web install --frozen-lockfile
$env:JAVA_HOME = '你的JDK21目录'
.\java\mvnw.cmd -f java/pom.xml -B -ntp -DskipTests package
```

政策检索使用固定revision的BAAI/bge-small-zh-v1.5，模型不入Git。首次下载需要网络：

```powershell
uv run --project agent --frozen --extra retrieval python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5', revision='7999e1d3359715c523056ef9478215996d62a620', local_dir='tmp/c071-probe/models/BAAI--bge-small-zh-v1.5')"
```

本机启动器沿用此路径，不能用空目录或假向量代替。

## 首次初始化

以下仅用于新的、无需保留数据的本机演示环境。reset备份后清除该演示库交易并重建基础数据，普通重启不要执行。

```powershell
docker compose -f infra/compose.reviewer-demo.yaml up -d
# 等待MySQL/PostgreSQL/Redis healthy后：
.\manage.ps1 reset -ClearDemoData
.\stop.ps1
```

初始化导入三店商品、14账号和政策并建立索引，不需要真实模型密钥。运行标记、数据库和索引留本地。缺少基础标记或索引时日常启动明确失败，不自动清库。

## 从旧买家身份升级

已有旧版数据时，先用旧版本处理完在途调查和咨询，再停止应用并备份 MySQL 与 PostgreSQL。只启动同一环境的两个数据库；下面示例使用原演示环境，拍摄环境须将两个容器名一起替换为 `resolveflow-recording-v1-*`。不要执行 reset。

```powershell
agent/.venv/Scripts/python.exe scripts/buyer_identity_migration.py --mysql-container resolveflow-review-demo-mysql-1
agent/.venv/Scripts/python.exe scripts/buyer_identity_migration.py --mysql-container resolveflow-review-demo-mysql-1 --postgres-container resolveflow-review-demo-postgres-1 --stage-map
```

首条命令只检查归属。确认 `ready: true` 后，第二条把同一份旧身份映射写入两个 MySQL schema 与 PostgreSQL。用新源码重新构建并启动，Case V38、Commerce V22 和 Agent 015 会追加迁移。遇到未知归属或活动 run 时先停在维护窗口核对，不要清库、跳过 Flyway 或混用旧应用。升级后买家用原账号重新登录；当前协议使用 `buyer_id`，所有启用的商家都可购物。旧映射只用于审计与接续旧咨询记忆。历史 strict 回放包仍使用生成它的运行版本；新运行不会替换旧包或重算请求哈希。

## 日常启停

```powershell
$env:RESOLVEFLOW_MODEL_API_KEY = '你的模型密钥'
.\start.ps1
.\status.ps1
.\stop.ps1
```

也接受Windows用户环境变量Deepseek_API_KEY。默认客服orchestrated-v1，新消息和待调查任务会调用模型；缺密钥不会假装启动完整Agent。status只读、不调用模型；stop停止所属应用和容器并保留卷。

```powershell
.\start.ps1 -NoBrowser
.\start.ps1 -SkipBuild # Java源码未改且已经构建时
```

启动MySQL/PostgreSQL/Redis/RocketMQ、三个Java服务、Agent与网页。网页 `http://127.0.0.1:5174/#/shop`，Gateway `http://127.0.0.1:8180`，日志 `tmp/reviewer-demo/logs/`。旧内部项目名resolveflow-review-demo用于保留数据归属。

PostgreSQL 使用 `127.0.0.1:55533`，避开 Windows 保留的旧端口55433；普通启动沿用原 `demo-postgres-data` 卷，现有记录与政策索引保持。

## 公开商品缓存

日常启动器已开启评价缓存，商品详情缓存默认沿用该开关。公开商品详情及图片/参数资料先读 Redis，未命中回源，TTL 为60秒；评价默认10条首页独立缓存30秒。其他评价分页继续查库。命中时不读取 MySQL 评价版本，公开展示以外的报价、结算和权限校验使用原领域服务。

商品资料、规格价格、上下架、店铺名称/启用状态、评价及回复修改，在业务事务中记录待失效项，提交后立即清理对应缓存。新增 Commerce V23 保存待失效记录；后台每2秒处理一批20条，再次失效并条件清理记录，失败项保留重试，缓存自身按 TTL 到期。提交回调只访问 Redis，不再申请数据库连接；后台的 Redis 调用也放在数据库事务之外。Redis 内的代次标记及条件回填拒绝失效前开始加载的旧结果。更新至失效完成之间及故障时允许短暂展示旧数据，成交金额由结算重新核验。

`CATALOG_CACHE_ENABLED` 可单独控制商品展示缓存，未设置时跟随 `PRODUCT_REVIEW_CACHE_ENABLED`。`PRODUCT_REVIEW_REBUILD_LOCK_ENABLED` 控制重建协调，缓存异常使用有限回源。普通启动会执行 V23；已有数据无需 reset。本批只验证功能正确性，旧性能实验对应其原冻结版本。

商品展示和评价的缓存重建锁均最多等100毫秒，不再设置固定2秒租约，采用 Redisson 默认30秒看门狗窗口自动续期。正常或异常结束均在 finally 中按所有权解锁；客户端停止后续期停止，锁按剩余 TTL 到期释放。看门狗不是业务超时机制，续期失败仍依靠所有权检查及代次校验限制旧执行者回填，旧固定租约实验不直接代表当前实现。

## 独立拍摄数据

2026-10-31已准备 `resolveflow-recording-v1`：独立MySQL、PostgreSQL、Redis、RocketMQ、图片目录及退款provider文件，沿用相同应用与端口。选择记录在忽略文件 `tmp/active-recording-stage.json`；存在时，正常start/status/stop以及物流模拟器均使用拍摄环境。两套环境轮流占用这些端口，原验收卷完整保留。

拍摄账号为 `display01`（卡皮巴拉），商家admin01–admin03、平台platform，口令按作者指定为123456。初始买家购物车/订单/咨询/售后/消息为空；商家仅三笔已签收背景订单，商品有三条评价、两条回复；平台没有客服运行记录。正常启停保留拍摄中新增的订单，不自动重置。

```powershell
.\status.ps1
.\start.ps1 -SkipBuild -NoBrowser
# 仅在第一笔拍摄交易之前检查初始状态；已经拍摄后不再要求零订单：
agent/.venv/Scripts/python.exe scripts/recording_reviews.py --verify
```

需要切回原验收数据时：

```powershell
agent/.venv/Scripts/python.exe scripts/recording_stage.py select-original
.\start.ps1 -SkipBuild -NoBrowser
# 再切回现有拍摄数据，保留拍摄进度：
agent/.venv/Scripts/python.exe scripts/recording_stage.py select-recording
.\start.ps1 -SkipBuild -NoBrowser
```

首次准备另有显式 `recording_stage.py prepare` 与 `recording_reviews.py`，本机已经完成，不重复运行。初始化仅复制结构、目录、身份、默认地址、图片及精确政策索引；背景订单和评价由正常业务接口生成。不使用旧reset命令清理拍摄数据，不在原数据库删除历史。准备中断会保留目录并拒绝覆盖，需先检查错误，不以重建卷处理。

## 体验

本机初始演示口令123456：买家buyer01–buyer10、商家admin01–admin03、平台platform。

买家浏览商品、按店结算/模拟付款；从订单行咨询Agent，核对并确认人工核查或退款摘要。商家查看事实和建议、核验/审批，Java执行模拟退款，买家查看进度。商家只访问本店，平台管理账号而非代审批。签收后可评价；受控履约工具见 `scripts/logistics_simulator.py --help`。

仅验证源码/核心服务且不调用模型，按[开发验证](development.md)操作，不等同真实模型质量或完整商城初始化验收。

## 精选商品与保留数据更新

当前新初始化目录采用三店、12款商品、15个在售SKU，清单在 `fixtures/catalog/collection-v1.json`。每家四款，耳机/键盘/双肩包双规格，其他单规格。价格单位仍为整数分；限购沿用原规则。

已有30款商品的本机环境不要重新初始化。三Java服务就绪后执行：

```powershell
agent/.venv/Scripts/python.exe scripts/catalog_collection.py
agent/.venv/Scripts/python.exe scripts/catalog_collection.py --apply
```

默认仅预览；apply通过本机8180的商家登录/商品管理API更新，先完整校验基础商品身份，再按expected_version写入，失败即停止，重新执行只处理剩余差异。原商品快照自动留在忽略的 `tmp/catalog-collection/`。只下架非精选基础商品及规格，保留全部原SKU、当前价格、用户自建商品、购物车、订单和退款数据；商品被改名或规格身份变化时拒绝自动覆盖。

维护命令不调用模型、不生成交易、不触发退款，也不自动启动调查worker。新初始化与已有数据更新是两条独立路径，普通start不重复执行目录更新。
