# 旧评测入口已退役

2026-10-05。旧H1的12个输入、Gold、记录schema及作者脚本已按用户授权先备份再移除，不再作为活动评测输入。备份/sha256清单见[清理记录](../../reports/current-evaluation/cleanup.json)。

当前唯一评测数据在[evals/current](../current/README.md)：32个案例/16对、60查询、六政策版本和独立Gold。根目录使用 `./eval.ps1`，具体见[指南](../../docs/evaluation-guide.md)。旧测试的泄漏/主体/配对区分安全要求已迁入新数据校验测试；兼容业务fixture及旧验收报告保留，不据旧成绩宣称当前效果。
