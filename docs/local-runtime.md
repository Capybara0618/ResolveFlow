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
.\demo.ps1 reset -ClearDemoData
.\stop.ps1
```

初始化导入三店商品、14账号和政策并建立索引，不需要真实模型密钥。运行标记、数据库和索引留本地。缺少基础标记或索引时日常启动明确失败，不自动清库。

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
