# Agent体验服务启动（2026-10-30）

用户要求启动Agent以自行体验对话。原前端/Gateway/Case/Commerce及MySQL/Redis/RocketMQ均运行，Agent8182与PostgreSQL未运行。

## 原因与处理

Windows TCP保留范围55362–55461覆盖旧PostgreSQL55433，实际55533绑定探针成功。将reviewer_demo.DEFAULT_PORTS与Compose默认映射同步为55533，仍只绑定127.0.0.1，正常start/status/stop归属检查保留。没有删除保留端口或更改系统网络保护。PostgreSQL容器按Compose重建，前后核对同一卷resolveflow-review-demo_demo-postgres-data；未清库、重建索引或重播旧调查。

## 验证

- `uv run --project agent --frozen pytest agent/tests/unit/test_project_runtime.py agent/tests/unit/test_reviewer_demo_driver.py -q`：42项通过。
- `docker compose -f infra/compose.reviewer-demo.yaml up -d postgres`：成功，健康healthy，映射127.0.0.1:55533。
- `.\start.ps1 -SkipBuild -NoBrowser`：退出0，复用现有三Java/前端进程，启动agent-live/orchestrated-v1。MySQL、PostgreSQL、Redis、消息服务、Gateway、Case、Commerce、Agent、网页、基础政策精确版本索引全部PASS。启动日志tmp/agent-experience-start-20261030.log。
- GET http://127.0.0.1:8182/health：200，status UP/service agent-service/support_architecture orchestrated-v1。
- 本次未代买家发送消息；健康检查没有调用模型，不将服务就绪写为真实对话质量复验。服务保持供用户体验。

实际密钥仅由既有启动脚本读取进程/用户环境，未打印或入库。本批仅提交端口映射、启动说明和报告；原4个无关脏文件保持。
