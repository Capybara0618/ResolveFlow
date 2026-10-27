# 校准评测版本 v2

使用说明见[开发验证](../../docs/development.md)，协议/Gold变更见本地历史规格，实际失败与诊断见报告（原始说明留本地）。

案例首次输入包含 `review_context`，材料查询返回引用列表；Gold独立保存，禁止注入。基础资产由 `manifest.json` 固定，当前五个持久回放由 `replay/manifest.json` 及包内 `files.json` 固定。合成材料hash不是Java真实提交记录hash的复现；资料和Gold尚未有人类独立签审。

原 `evals/current` v1 保留，不能将两版成绩当算法前后提升。新修改须另发布版本，不能覆盖已冻结文件。复建流程是新目录 `build_alignment.build(directory)` → 隔离PG下导出五个 `test_golden_trajectory` 包 → `freeze_replay(directory)` → 校验；日常评测不执行复建。

当前公开入口与边界见[开发验证](../../docs/development.md)和[精选结果](../../docs/evaluation-results.md)。
