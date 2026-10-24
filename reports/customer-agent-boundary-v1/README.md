# 客服共同边界修复证据

2026-10-24，依据[本批方案](../../docs/customer-agent-boundary-v1.md)。原[44轮评测](../customer-current-evaluation-v1/README.md)保留；本目录记录新工程行为，不覆写原模型答案或算成新模型成绩。

## A：理解前的真实应用上下文

- 原因：get_support_guide只在部分已接受意图后自动读取；理解之前不具备指南，stage.project还会剥离所有Observation。只提前调用工具、不改实际投影，模型依然看不到。
- 实现：仅orchestrated-v1在驱动前读取原指南一次，经原预算/journal；理解投影仅恢复已核对GUIDE原文，application_context分开可信当前对象、默认对象及是否有单。提示明确隐私/共享/接续属于GUIDE、退款政策条件属于POLICY；没有关键词路由或固定业务工具路径。
- 新测试最初5失败，见[红测](application-red.txt)。初实现2失败/29通过，暴露stage剥离；补实际Observation后另一字面JSON空白断言失败，改解析实际发送JSON后，三文件31通过，见[最终](application-tests.txt)。原纯政策测试仅更新新增公共本地读预期，保留无订单/物流和相关政策引用断言。
- 命令：根目录`PYTHONPATH=仓库根`、`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_application_context.py agent/tests/unit/test_support_orchestrated_engine.py agent/tests/unit/test_support_orchestration.py -q --tb=short`。agent目录Ruff上述三源码/两测试通过，strict mypy三源码通过。首次从根目录指定Ruff配置造成两个测试导入分组诊断，切agent目录按实际配置检查通过，未改变业务。保留Starlette既有弃用警告。
- `docker ps`失败：Docker Desktop LinuxEngine管道不存在；本步未运行PG/API恢复或Java/Web集成，不把skip算通过。单元中的真实SDK循环与脚本模型不等于真实模型语义改善。新增Provider调用0，账本2274；原四脏文件/旧报告保持，未重启正常项目或修改业务数据。
- 代价：即使纯政策也多一次本地指南读取及上下文，模型请求数不增加。范围为“理解前资料可用/可信对象有区别”，不是保证模型会选对。B的解释/步骤/正文合同仍按方案实施，当前任务进度只见todo顶部。
