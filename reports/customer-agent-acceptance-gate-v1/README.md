# 客服 Agent 小规模真实验收

2026-10-24，用户批准执行[验收协议](../../docs/customer-agent-acceptance-gate-v1.md)。实际进度仅 tasks/todo.md 顶部。

## 主链路准备

开工main/origin/main=d99fb4d、fetch后0:0、暂存空；只保留原四历史脏文件和已有未跟踪资产，未发现同文件业务并行写入。status全部健康，生产最终反馈修复已加载；本批不改任何生产Agent/RAG/Java/Web源码或预算。

新驱动`accept_customer_agent_gate_v1.py`复用原购买准备/费用账/数据保留收集，独立目录保存；`check_customer_agent_gate_v1.cjs`沿已验证真实浏览器流程，增加自动摘要编辑刷新、确认/同键恢复、正常首次MANUAL_REVIEW与未核验陈述检查，不做商家核验/审批/退款。原驱动与旧失败保持。

实际命令：新Python `ruff format`、`ruff check`、`py_compile`及新CJS `node --check`通过；`git diff --check`通过。曾定位一个不存在的旧CJS文件及PowerShell通配路径，改用rg定位当前文件，只读无业务影响。没有修改生产源码，不重复旧全量回归。

`python scripts/accept_customer_agent_gate_v1.py prepare`完成一笔新329元已付已发/LOST合成订单，[冻结计划](primary/plan.json)绑定全部support源码和4驱动文件SHA、13保护文件SHA。0模型，usage2098；至多1客服run及1自动初始调查。A完成且原文/来源审核通过后才准备B–D；原文已在协议预先固定，不按A输出改控制题。

准备文件精确提交、普通push核实后仅执行一次。自动摘要未生成时不点击手动申请或编造原因继续；所有失败/未知调用都保存，已见问题的确认不当简历成绩。

## 一次真实结果

准备8af7335已同步。`execute`返回失败：4真实请求、准确10032输入/528输出、0未知，usage2098→2102；候选缺少退款操作声明，摘要语义前置检查的普通ValueError绕过完整缺项诊断，反馈误归为citations。模型修正只删摘要，未补ORDER/GUIDE及操作，未正式发布。没有生成草稿/新Case/退款，B–D未启动。[全部证据与未运行项](primary/README.md)。原数据/索引/13保护文件保持，无在途。先精确保存失败并普通push核实，再做离线诊断修复；本轮不自动重发收费题。
