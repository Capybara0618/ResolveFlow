# 发布规则修正与针对性真实确认

2026-10-23，生产426f08c，准备0cdfe96。按[本批方案](../../docs/customer-agent-publication-v2.md)和[冻结清单](../../evals/customer-agent-publication-v2/manifest.json)只执行一次四轮自然对话及一个单独恢复探针。**自然四轮全部发布且源审完整；R01真实模型先补读指南、再引用实际来源，最终成功发布。当前个人项目限定场景可阶段性冻结Agent实现、提示与配置，转量化评测和演示整理。** 不再扩架构或为非阻塞措辞问题继续收费迭代。

## 修正内容

原条件“解释含页面名就拒绝”改为同part页面与结构化操作相符：售后咨询对应MERCHANT_REVIEW，我的售后对应REFUND_APPLICATION；来源须实际读取、内容/版本一致的受控指南。正确页面说明可以发布，程序继续生成固定步骤/确认边界；无读来源、缺必需操作、状态不允许、同段动作重复、直接错页/按钮对仍拒绝。没有用正则把错误答案替换成正确答案，没有增加模型阶段或另一套循环。

错误反馈的只读诊断共用有效next_steps引用合并，避免已读指南在渲染前被误报缺失。提示和修复反馈允许正确页面说明。有限UI配对规则无法理解任意同义路线、多句指代或否定句，不作为通用语义正确性证明。

## 真实结果

| 场景 | 结果 | 实际行为 |
| --- | --- | --- |
| A01-1 未收到、查询运输 | 发布/完整 | 自主读物流，承运DELIVERED与客户陈述分开，三项事实独立保存 |
| A01-2 暂停插问退款入口 | 发布/完整 | 原t1暂停、新t2读指南，选REFUND_APPLICATION，正确“我的售后”说明直接发布，无旧误拦 |
| A01-3 恢复核查并更正代收情况 | 发布/完整 | 原t1恢复OPEN，家人旧确定陈述REPLACE为尚未问清，保留门卫排查；物流/指南齐全，人工核查入口正确 |
| A01-4 再确认无人代收、只核查 | 发布/完整 | 再次REPLACE家人陈述；facts首次缺占位符，唯一反馈后实际模型修正并发布，入口/确认边界一致 |
| R01 显式缺指南恢复探针 | 单独完整通过 | 两条mock前缀触发真实反馈；第一条真实决定读指南，第二条引用实际O1并选MERCHANT_REVIEW，正确页面说明成功发布 |

[完整对话](conversations.md)、[逐项源审](review.json)、[统计](statistics.json)、[自然raw](natural-results.json)和[恢复raw](repair-results.json)保存实际请求、原始模型决定、工具结果与PG持久调用账。源审为Codex逐条核对，非独立人工Gold。问题为前批已见合成业务场景；自然4/4不外推整体成功率，探针不并入“5/5准确率”，本批不提供简历量化结论。旧3/4与失败探针原文/清单/评分保持，没有回填。

R01的理解和第一次未读取来源的错误答复来自两条SCRIPTED_FAULT_INJECTION/mock记录，零Provider请求；模型只自主生成随后的补读和回答两条。不隐藏、替换或丢弃任何真实供应商响应，注入消耗原Harness预算但不计Provider Token/请求。

A01-4首次提供facts但正文直接写DELIVERED，程序拒绝；反馈要求占位符，真实模型在唯一修复内补齐并成功发布。原错误、反馈及修复均保留。source_gaps中的SHIPMENT在这里表示被拒part没有完成事实引用合并，不表示实际物流未读取，不能误归为RAG/物流读取故障。此前已有指南的next_steps误报本批未再触发。

非阻塞观察：部分回答重复程序生成的步骤；A01-3可选门卫陈述误用CONTINUE，有warning并保留旧事实/原文，不算更新成功；A01-4对门卫的新确认合法替代旧条。两次家人REPLACE、暂停恢复和关键指引实际有效；不宣称任意主题的长期记忆或全场景客服已成熟。这些问题不继续阻塞个人项目收口。

## 工程验证与效率

新13项先7失败/6通过，实现后集中客服单元及导航、两阶段、会话更新、受控恢复PG283通过（9.64秒）；相关Ruff与4源码strict mypy通过。最初联合测试漏PYTHONPATH导致脚本模块收集失败，补环境后两个恢复测试因更换mock脚本被manifest正确拒绝，改为沿用原脚本后通过；没有放宽恢复条件。新准备/原验收与导航PG9通过（4.99秒），相关Ruff通过。

[保存轨迹复核](previous-paths.json)在当前正式规则下让上批四轮/探针原决定全部可发布，没有临时关闭谓词；这是离线诊断，不是strict回放或新的真实成绩。此前旧混用页面决定的回归仍拒绝。执行前后清单、模型权重与数据库预检通过。

17真实deepseek-flash请求，Provider输入44536/输出1832、estimated=false，usage1994→2011；另2mock注入，总SDK19决定/7工具，5run/26调用账导出。自然四轮19.773秒、预热9.000秒、探针3.054秒分别列示；Harness保守输入自然46716、探针8841（含注入前缀）另列，不混成Provider计数。少量单次观测，不作延迟SLA或降本结论。

本批真实模型、AgentScope 2.0.8、ASGI与隔离PG；指南来自正式版本2026.10.22-v2，Commerce/Case为原固定合成HTTP。没有启动Java/网页，没有执行退款/分享写入或进行RAG检索效果、压测验收，不替代此前双端业务证据。

## 冻结与数据保全

冻结说明见[Agent阶段冻结](../../docs/customer-agent-freeze-v1.md)。生产源码保持426f08c，清单SHA256为`b28b708ac5d18d62965424a4e537000b519129b769880095da5ec573bc38f814`。后续量化时复用此实现，另建评测清单，不为成绩修改旧报告或静默升级未完成run。

[保全指纹](preservation.json)记录public11表全行hash和原四脏文件/旧raw/旧清单/旧诊断共14文件，执行前后相同；自有schema在完整导出后清理。原卷、政策、数据、旧失败和简历保持；本轮收尾停PG保留卷，原Java/网页维持关闭。最终容器/端口/用量锁核验见任务账本。

raw SHA256：自然`d762af26155f53249eca0bbd29c8f123a0542ccd12ae762c61c6ea995fd2f867`，探针`c6e8ca0dfed8583830550563807e123865b5365598de800586e8535309847cdf`。

主要实际命令（execute已执行，不重新调用）：

```powershell
# agent目录，按既有环境配置实际PG与PYTHONPATH
.venv/Scripts/python.exe -m pytest $suite tests/integration/test_support_navigation_publication.py tests/integration/test_support_staged_api.py tests/integration/test_support_conversation_update.py tests/integration/test_customer_agent_acceptance_v1.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_publication_v2.py tests/unit/test_customer_agent_acceptance_v1.py tests/integration/test_customer_agent_acceptance_v1.py tests/integration/test_support_navigation_publication.py -q
# 根目录，数据库预检需要原PG已启动
agent/.venv/Scripts/python.exe scripts/customer_agent_publication_v2.py --check --database
agent/.venv/Scripts/python.exe scripts/customer_agent_publication_diagnose_v2.py --output reports/customer-agent-publication-v2/previous-paths.json
```
