<p align="center">
  <img src="docs/assets/readme/readme-hero.png" alt="ResolveFlow：让购物与售后，顺畅衔接。Java 微服务、Agent 智能客服、开源商城。" width="100%">
</p>

## 完整演示

https://github.com/user-attachments/assets/34304069-e2da-4552-ac25-2443e1b759d3

## 关键流程

![物流咨询、退款确认、商家审批与退款结果](docs/assets/readme/walkthrough-25fps.gif)

## 三端体验

![买家商城](docs/assets/readme/buyer.png)

<p align="center">买家</p>

![商家审批](docs/assets/readme/merchant.png)

<p align="center">商家</p>

![平台咨询运行记录](docs/assets/readme/platform.png)

<p align="center">平台</p>

## 技术栈

<picture>
  <source media="(max-width: 600px)" srcset="docs/assets/readme/tech-stack-mobile.png">
  <img src="docs/assets/readme/tech-stack.png" alt="Vue 3、TypeScript、Vite、SSE；Java 21、Spring Boot、MyBatis，Gateway、Case、Commerce 三个微服务；Python、FastAPI、AgentScope、MCP、Agent Harness；pgvector、BGE、BM25、RRF、CrossEncoder 检索与评测；RocketMQ、Outbox/Inbox、Redis、Redisson、Lua；MySQL、PostgreSQL、Docker。" width="100%">
</picture>

## 微服务架构

![Gateway 统一接入，Case 管理工单与审批，Commerce 管理订单与退款，Python Agent 查询事实与政策并生成建议；HTTP 与 RocketMQ 衔接服务。](docs/assets/readme/architecture-rounded.png)

## 核心设计

<picture>
  <source media="(max-width: 600px)" srcset="docs/assets/readme/core-design-mobile.png">
  <img src="docs/assets/readme/core-design.png" alt="Agent 自主决策：咨询成功率46.9%→87.5%；Agentic RAG：Top-3关键证据完整命中率75.0%→84.4%；交易一致性：160轮竞争测试，重复订单与扣款均为0；异步可靠退款：80笔订单行测试，重复与超额退款均为0；上下文与恢复：上下文通过率68.8%→90.6%；SQL与Redis：30并发订单查询p95从2441降至755ms。" width="100%">
</picture>

## 快速开始

```powershell
$env:RESOLVEFLOW_MODEL_API_KEY = '你的模型密钥'
.\start.ps1
```

<p align="center">
  <a href="docs/local-runtime.md">运行指南</a> ·
  <a href="docs/system-design.md">系统设计</a> ·
  <a href="docs/evaluation-results.md">评测结果</a>
</p>
