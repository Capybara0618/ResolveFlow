# ResolveFlow 本机启动

在项目根目录打开 PowerShell，先启动 Docker Desktop，然后运行：

```powershell
.\start.ps1
```

这是日常运行入口。它启动 MySQL、PostgreSQL、RocketMQ、Gateway、Case、Commerce、Python Agent 和网页，检查基础政策的精确版本索引，自动打开商城 http://127.0.0.1:5174/#/shop 。Agent 默认使用现有 DeepSeek Flash 配置处理新调查，读取真实订单、材料及政策，再向商家提交建议。人工审批和 Java 模拟退款仍走原有权限与资金约束。

开启政策索引时，Python Agent 启动会先预热客服共享的本地 embedding 和 BM25 分词器，日志显示 `support_embedding_warmup status=WARMING/READY` 及耗时，就绪后才接受请求。预热不访问生成模型或数据库；权重缺失或损坏会使启动失败。可设置进程环境变量 `RESOLVEFLOW_SUPPORT_PREWARM=0` 保留惰性加载，此时首次政策检索会承担加载耗时。启动预热会增加启动等待时间，并不保证生成模型或数据库的后续响应速度。

启动自动读取 Windows 用户环境变量 `Deepseek_API_KEY`，也接受进程中的 `RESOLVEFLOW_MODEL_API_KEY` 或 `Deepseek_API_KEY`。密钥不写入源码、命令参数或报告。缺少密钥时启动明确失败，不切换到功能不全的只读模式。新申请和补证后的调查会产生模型用量；启动和状态检查自身不发送测试模型请求，已有待调查任务会被 worker 消费。

```powershell
.\status.ps1              # 所有组件就绪返回0，否则返回1；不调用模型
.\stop.ps1                # 停止本项目应用与依赖容器，保留数据卷
.\start.ps1 -NoBrowser    # 全部功能照常启动，只是不自动打开浏览器
.\start.ps1 -SkipBuild    # 已构建且Java源码没有变化时可用
```

重复启动复用健康的所属进程。停止、重启不会重建账号、商品、订单或工单，不生成验收交易。已有健康的 Java 服务会继续复用；修改 Java 源码后先停止再启动，默认重新构建。当前功能仍是个人项目的本地运行，支付、发货和退款为模拟操作；正式入口名称不表示已完成公网生产部署。

## 首次配置

当前电脑已配置依赖和基础数据，可以直接使用 `start.ps1`。新电脑需要 Docker Desktop、JDK21、Node/pnpm、项目锁定的 Python 环境 `agent/.venv` 和本地政策 embedding 快照；Java/pnpm/Python 的依赖安装沿用[工程说明](engineering.md)，不得更换锁或使用假检索代替缺失模型。首次启动会构建 Java 包并在缺少 `web/node_modules` 时安装锁定依赖。

基础数据初始化与日常启动分开。没有 `tmp/reviewer-demo/foundation.json` 或未升级为三角色时，启动拒绝自动覆盖数据。仅对**已确认无须保留的本地环境**，使用原维护工具显式备份并初始化：

```powershell
.\demo.ps1 reset -ClearDemoData
.\stop.ps1
.\start.ps1
```

`reset` 会清除隔离环境的交易并重建基础数据，因此不能用于普通重启或修复启动失败。现有电脑不需要执行它。基础配置为3店、30商品、45SKU、10买家、3商家和1平台账号；密码与操作见[体验指南](clean-demo-experience.md)。新店政策仍需受控准备。

## 诊断与维护

启动异常会返回失败和具体原因，查看终端及 `tmp/reviewer-demo/logs/`，排查 Docker、占用端口、依赖或密钥；不要用清库来解决一般启动问题。服务状态包含 Agent 是否为真实调查配置、数据库/消息服务、三个 Java 服务、网页及基础政策索引；健康检查不保证模型提供方可用或每次调查成功，实际结果以工单与轨迹为准。

原 `demo.ps1` 保留为只读、合成验收和显式数据重建的维护工具。当前容器项目名 `resolveflow-review-demo`、运行目录 `tmp/reviewer-demo` 和端口保持不变，以继续使用已有数据库和备份；它们是内部兼容名称，日常使用无需记忆。
# 2026-10-22 后端深化补充

本项目独立 Compose 新增 Redis7.4，绑定 `127.0.0.1:56380`，与共享环境56379隔离；缓存丢失可回源，不挂业务数据卷。正式 Case 启动启用工作台展示缓存并指向此端口，status 将 Redis 纳入健康检查。已有进程需要按正常 stop/start 重启后加载新代码；此次实施只验证独立 Redis ping/停止及启动接线测试，未启动真实模型或将历史压测数作为当前性能。
