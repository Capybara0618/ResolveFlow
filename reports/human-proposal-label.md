# 人工方案来源标识修复

2026-10-02，第五批正式网页失败样本9acdb393-40b2-423a-b0ec-08781a92254f，人工方案已保存为HUMAN、第3版，但政策三层区的标题仍写“Agent解释”，把人工理由归给模型。ReviewerWorkspace现在按持久origin显示人工方案理由；AGENT原有标题保持。

实际命令：`pnpm --dir web test -- tests/reviewer-workspace.spec.ts`先1 failed/14 passed，新增回归重现人工来源误标；修复后`pnpm --dir web test`109 passed/16 files，`pnpm --dir web build`通过类型检查和构建。此改动只修来源文字，不改变方案、审批、金额、调查版本或权限。全批真实流程另见最终整体验收报告。
