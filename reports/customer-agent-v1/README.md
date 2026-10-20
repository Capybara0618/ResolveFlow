# 客服Agent / RAG接入证据

2026-10-20。[实施设计](../../docs/customer-agent-implementation-v1.md)，进度仅[todo顶部](../../tasks/todo.md)。本报告将工程接线、脚本模型与真实模型质量分开。

## 咨询循环与来源适配

新增Python support/protocol.py、engine.py与sources.py，AgentScope Agent驱动READ_TOOL/SEARCH_POLICY/ANSWER，复用现有AgentScopeModelAdapter/ModelClient/BudgetGuard/输入计数及PolicyIndex。模型自主选择读取/检索，咨询不创建虚假Case/退款方案；订单、物流、历史只走绑定咨询run的Case facade。政策采用dense及商家/bundle/manifest/generation前置过滤，不回退其他租户或BM25。

新单元19项通过：动态物流/政策选择、无需强制搜索、拒绝写工具/身份覆盖/假引用、预算/过期/超长、查询失败、完整实际输入计数、HTTP来源失败/旧输入及检索过滤。全部模型为明确mock，不能作为客服质量分数；Java/API/PG/网页连接和真实dense验证由后续本批步骤完成。

红测因模块不存在失败；首版工具停止异常触发SDK已安装MCP异常别名问题，改为工具错误观察并在下一模型调用前终止，未修改SDK或安装依赖。来源适配首版误用旧异常类名、测试导入路径及Ruff排序已修正；日志保留忽略目录`tmp/customer-agent-design-v1/assistant-*`。当前引用验证证明来源存在/绑定，尚不等价于每句自然语言均被引用语义支持。

本步骤未调用付费模型、未运行后台worker或修改现有数据/简历/Gold；生产旧Case循环与协议保持原实现。正式接线前还需PG调用账与旧输入发布验证。
