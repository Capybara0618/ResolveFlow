# ResolveFlow｜多商家电商与智能售后平台

覆盖商品浏览、按店购物车、模拟付款、订单评价，以及Agent咨询、政策检索、人工审批和可靠模拟退款的个人项目。

Gateway、Case、Commerce三个Java服务与Python Agent协作，Vue 3提供买家、商家和平台管理页面。Java持有权限、授权与资金，Agent读取事实并提出建议。

本页暂为精简后的运行导航，产品横幅、真实演示动图与展示页面另行制作。

| 内容 | 入口 |
| --- | --- |
| 安装、初始化、启停 | [本机运行](docs/local-runtime.md) |
| 架构与业务边界 | [系统设计](docs/system-design.md) |
| 构建、测试、CI | [开发验证](docs/development.md) |
| 实测与口径 | [精选结果](docs/evaluation-results.md) |
| 目录与本地资料边界 | [仓库说明](docs/repository.md) |
| API与数据协议 | [核心契约](contracts/core) |

完整安装与首次初始化先读运行说明。Windows PowerShell日常入口：

```powershell
.\start.ps1
.\status.ps1
.\stop.ps1
```

网页：`http://127.0.0.1:5174/#/shop`。需要Docker、锁定依赖、政策embedding快照和基础数据；Agent使用自行配置的模型密钥，新消息/调查可能产生提供方费用。

支付、物流和退款均为本地模拟，指标来自合成场景。没有公网托管服务。Linux CI提供构建和核心API冒烟；完整本机商城启动入口目前为Windows PowerShell。
