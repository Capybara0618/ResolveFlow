# C10 strict 回放

`golden/` 存放五条从独立 PostgreSQL 测试 schema 中完成的合成 run 只读导出的 ReplayPack。每包有独立 `evaluation_run_id`、原 run ID、冻结的 manifest/预算/实验时钟、实际模型请求及显式响应、工具请求及 Observation、usage、终局回调与 SHA-256 文件清单。五包均用生产 AgentScope 2.0.8/Harness 循环重放。

在仓库根目录运行：

```powershell
agent/.venv/Scripts/python.exe -m resolveflow.replay.cli strict evals/replay/golden/manual_review
./scripts/replay_strict.ps1 evals/replay/golden/manual_review
```

第二条在无网络、只读、非 root 容器中重放。其他包名称为 `question`、`escalation`、`read_then_review`、`read_then_question`。重新生成包须有可用的测试 PostgreSQL，并显式设定 `RESOLVEFLOW_REPLAY_GOLDEN_DIR` 后运行 `agent/tests/integration/test_replay_golden.py`；现有目录不会被覆盖。生产数据不得进入此目录。

导出一个**已完成的合成 run**：

```powershell
agent/.venv/Scripts/python.exe -m resolveflow.replay.cli export RUN_ID OUTPUT_DIR --synthetic-ack
```

只支持同 manifest 的完整顺序 mock 轨迹。历史不兼容版本、live 响应、缺失或本地工具记录会明确拒绝；不提供反事实回放。
