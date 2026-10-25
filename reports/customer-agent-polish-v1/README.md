# 客服等待与呈现根因核查

2026-10-25，输入为原[页面真实请求](../customer-latency-browser-v1/runtime-results.json)，不重写旧结果。脚本`scripts/diagnose_customer_wait_v1.py`只加载持久决策/工具响应，在当前SDK重放，不连数据库/HTTP、不发模型请求；deadline仅在离线副本延长，原报告不改。

[修正前](before.json)：tokenizer首次加载305ms，已预热SDK/装配5次中位60ms，模型journal起点相隔2140.708/1244.753ms。这两个间隔不是精确供应商耗时，包含各自生成、校验与工具；不能由此证明TLS、RAG或首token各耗时多少。原Java日志首delta5429.744ms保持。计数器冷加载是可迁出的本地等待，串行模型链路是主要等待区间，仍需细分计时。

第一步：ground_answer可按(field,source_id)去重展示，但逐项原校验/引用/事实、原摘要均保持；engine只对orchestrated-v1打开。navigation在实际有refund_summary时采用准备卡片后的简短确认指引，保留异步准备和用户确认边界，不声称已提交或已创建卡片。无摘要和旧架构仍走原入口教程。

新增7测试先4失败/3通过，修正后与navigation/fact_fields/orchestrated_engine/orchestration共80通过。扩大全部unit的support匹配525通过/6既有跳过/1828未选，首次误指定不存在contracts目录而0测试，已纠正命令；不当全仓成功。[原决策修正后](after-presentation.json)仍3次脚本决策，最终506→448字符，重复物流字段2→1；退款摘要、记忆和dialogue逐字保持，模型两段解释未删除。离线耗时不作真实提速百分比。

Ruff五文件通过（首次pairwise规范已修正），生产三源码strict mypy通过。当前0新增供应商/业务写入，usage2378，项目保持关闭。后续按[本批设计](../../docs/customer-agent-polish-v1.md)接续冷启动预热和精确计时，不用降低输入校验/政策要求或重试刷分解决延迟。

## 冷启动与分阶段计时完成

呈现修正a442486已普通push核实后接续。正式live Flash在FastAPI lifespan就绪前加载同一锁定tokenizer，其他profile不加载、mock/预热关闭保持惰性、资产损坏失败而非静默退回估算；不请求供应商。`engine`记录每次实际模型调用的prepare/current/journal/provider/first_content，错误也计时，cached恢复明确0发送；实际工具读取单独计时。模型日志COMPLETE不代表答案通过，JSON首内容不代表DOM首正文，校验/settle等未单独计量边界仍明确。

新增最初7测试先7失败，扩展精确profile/真实MockTransport流式首内容4项，最终与原embedding/session共24通过；扩大support单元536通过/6既有跳过/1828未选，非全仓。3生产源码strict mypy及5文件Ruff通过（测试import顺序首次修正）。[实际FastAPI启动+原决策重放](startup-counter.json)显示加载256.655ms发生在READY前，cache misses在三决策后仍为1，三阶段本地prepare约10.6/8.8/34.7ms，没有第二次加载；模型为已存脚本，provider_ms不是真实模型延迟，不能据此声称首正文已达4秒。

PG初次Docker未启动：原55433只读快照PoolTimeout，测试3过/11因连接跳过，未生成快照。用户启动Docker后原端口落在Windows保留段55385–55484，原容器仍被拒绝bind；未改端口保留/防火墙/原数据卷/项目启动配置。使用原本地镜像ID（pgvector:pg16）在127.0.0.1:65433创建仅本批独立测试库；原5组API/流式/恢复14通过，新增恢复测试首次错误更换了manifest中的mock_script而正确被MANIFEST_MISMATCH拒绝，保持原脚本后单测通过。最终合计15项PG验证通过，未删断言或放宽manifest。

新恢复例真实PG journal重取租约，模型/工具全复用，三条cached=True且provider_ms=0，0新增脚本调用；原事实、摘要、spend和结果全等。临时t_ schemas全部删除、测试库public无业务表；原数据库未打开，不能宣称做过原public前后hash比较。测试容器已停止保留数据，原容器/卷保持，Docker留运行；项目全部服务未启动。本批0供应商/Java业务写入，usage2378，不追加付费题或新UI。剩余是供应商/串行生成主路径的真实耗时与回答自然语言精炼，已有仪表可以定位，但不宣称这些已修好。

本批命令：`pytest`新24针对、`pytest agent/tests/unit -k support -q`、5个原integration文件14通过及新`test_support_polish_runtime.py`1通过；`ruff check`、三源码`mypy --strict --follow-imports=silent`；受控FastAPI启动及保存决策重放；Docker同镜像独立测试库启动/停止。完整保护与资源状态见[audit](audit.json)。

收尾另查到默认Uvicorn仅配置自身logger，单独增加模块INFO调用不保证正式启动能看到计时。正式客服启动器现显式加载`infra/logging.agent.json`，只对engine/sources/app开放INFO并保留原Uvicorn配置，不将httpx等第三方全部打开；子进程真实加载配置验证计时/预热标记可见且httpx INFO不输出。新增日志配置测试及原启动器测试纳入最终39项针对通过；五个Agent源码/测试Ruff过，reviewer_demo全文件Ruff原19条已与HEAD逐项对照保持，无新增（[基线对照](launcher-lint.json)），不顺手清理旧问题。脚本py_compile通过。该配置确保下一次正式启动能获取诊断证据，不冒充已取得新真实模型时延。
