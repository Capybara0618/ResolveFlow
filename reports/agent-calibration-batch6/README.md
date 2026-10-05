# 第六批结果：输入契约、计量和修正反馈

2026-10-05，按[规格](../../docs/agent-calibration-batch6.md)完成本批实现和集中验证。当前 context v11/verifier v5，Flash 使用固定 hash 的官方 V4.1 tokenizer 本地估计，其他模型使用 UTF-8 上界；正式默认评测 calibrated-v3/strict calibration-v9。旧数据、Gold、报告、回放和日常工单均保留。

工程验证通过，真实建议质量仍未全通过。

| 验证 | 结果 | 证据与含义 |
| --- | --- | --- |
| 集中 Python 回归 | 710 passed，0 failed/errors/skipped | tests-final.xml/txt；包括 SDK、PG、MCP、恢复/fence、保护事实、合同、评分、引用及纠错；1个既有 AnyIO 弃用警告 |
| 独立 Harness | 28/28 | harness.json；权限/非法来源/终止不能绕过 |
| 新严格回放 | 13/13 | replay.json、新独立十三包；脚本模型/UTF-8回退，不宣称真实Flash轨迹已全回放 |
| calibrated-v3 脚本调查 | 32/32联合正确，150脚本调用 | mock-all.json；真实 PG/MCP/embedding 与脚本模型，不是 LLM 准确率 |
| 固定真实复测 | 10/13联合正确，3未完成，0接受禁止终局 | live-retest.json、audit.json、[逐例结果](cases.md)；原10个联合失败+3正向控制，分母全部保留 |
| 冻结资产 | v1/v2 hash 保持不变，新v3预检通过 | state-before-live.json/state-after.json；三商家、六版本、32例/16对、60查询 |
| Ruff / 差异检查 | 本批改动通过 | 使用 agent/pyproject.toml，原四个历史脏文件不夹带 |
| 全项目 mypy | **失败：9文件16个既有错误** | mypy.txt，73源码；本批2个新增诊断修正后消失，不称全项目类型门禁通过 |

真实模型使用 deepseek-flash 服务别名，temperature=0、thinking disabled、JSON output；非固定供应商模型快照。64次实际请求均有非估算 usage：输入106746、输出7951 token。历史 ledger 从252到316，limit=null，不清零；费用预留旧字段没有更新，不能当本次账单。

此前156次请求离线核对，官方 tokenizer 本地估计含预留均高于实际 provider 输入，最小余量409；本批64次最小余量376，没有上下文溢出或低于实际输入的估计。计数取完整 JSON 与分别编码的消息内容的较大值，加一次256包装预留，仍是 ESTIMATED，不是在线精确模板计数或对所有未来文本的数学保证。长中文 SDK+PG stub-transport 验证实际 body/预留/manifest 一致，返回后使用实际 usage 结算。

剩余三例如实保留：A01B/A02B 在沿用的评测每例6次调用限制下终止 BUDGET_MODEL_CALLS（生产默认12次；这是单工单终止界限，不是 API 消费额度）；A03B 两次输出错误地认为 RESERVED 行可退，被 UNSHIPPED_FACTS_REQUIRED 拦截后停止。它们没有被强行改成“模型已给人工建议”，也没有绕过检查、重置修正次数或再请求模型来刷通过率。下一步应针对具体失败字段改善修正反馈，并显式用生产调用配置测剩余案例；独立逐query Gold/语义人审仍未完成。

同13个编号在旧版本联合3/13、新版本10/13，但输入和源码均变更，这只是描述，不是受控质量提升结论。31普通合成样本+1未支付边界探针不是实际流量，独立人审0/13待填。RAG语料/Gold/正文dense排序没有修改；不将无终局引用称为召回失败。

初轮：新增模块尚未实现时两次收集失败；一次定向调用未设55433数据库环境而跳过1项，不计入验收，正式集中验证0 skipped；Ruff初次误用根配置后按Agent配置核验；全量初轮688通过/2失败，分别是表格引用可见性的旧呈现断言和更明确计量标签，修正后新增负向/PG/MCP测试一并710通过。Flash持久预留新增测试首次缺少DeploymentConfig配置且stub响应类型不完整，修正测试接线后6项通过。新回放manifest首次取错pack字段名，改用现有manifest字段冻结；原包未覆盖。mypy的2项新增错误（可选Section类型、依赖无stub）已修正。提交差异首次遇到复制血缘JSON的CRLF和失败XML的空白；新增仅作用于本批冻结目录的.gitattributes保留原始字节，仅清理本批诊断XML空白，最终staged哈希逐文件一致且diff通过。命令见commands.json，首次失败日志保留。

日常 public Agent 始终4 COMPLETED /15模型/10工具/8回调，无临时schema或usage锁遗留。未重启常驻worker、重算日常run、执行业务退款、Java整链、网页验收或完整32例Live；新代码下次正常启动加载。原四个工程/verify/Commerce测试及草图日志保持原归属。
