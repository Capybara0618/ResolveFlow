# Jev 客服回答辅助检查

2026-11-02。用户选择先完成可演示的实际接入，再按效果决定简历表达；不以研究规模评测或预设提升比例阻塞。保持现有 AgentScope 主循环、流式回答、Java 权限及退款职责。

## 采用方式

- TypeSafe 官方 `POST https://api.typesafe.ai/v1/systemone`，固定 `jev-1.14.0`；使用现有 httpx，不改依赖锁。
- 三分类 `supported / contradicted / insufficient_evidence`，只作回答与本轮材料一致性辅助检查。
- 模型置信度不等于正确率，更不等于退款授权；不自动拦截或改写买家回答。
- `.env` 只存本机密钥，Git 已忽略；服务不会在 import 时自动读密钥，启动入口显式加载允许的 Jev 配置，进程环境优先。

## 第一步：客户端与配置

文件：`agent/src/resolveflow/support/jev.py`、`agent/tests/unit/test_jev.py`。

实际命令：

```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_jev.py -q
.\agent\.venv\Scripts\python.exe -m ruff check agent/src/resolveflow/support/jev.py agent/tests/unit/test_jev.py
.\agent\.venv\Scripts\python.exe -m mypy --config-file agent/pyproject.toml agent/src/resolveflow/support/jev.py
```

15 项单元通过、Ruff通过；首次先红为模块不存在的收集失败。覆盖精确模型/官方端点、密钥不进配置快照、环境优先级、保留冲突/失败材料、实际 usage、HTTP302/401/402/429/500 不重试、不跟随重定向、不保存敏感错误正文、非法响应与超时不冒充语义结果。

本步尚未接入客服运行，不宣称业务完成或质量提升；本步无付费调用。先前单条官方连通验证不作为质量评测。

接口来源：[System One](https://docs.typesafe.ai/api/system-one)、[Choice](https://docs.typesafe.ai/primitives/choice)、[模型](https://docs.typesafe.ai/models)。
