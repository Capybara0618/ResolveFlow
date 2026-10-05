# Agent / RAG 评测使用指南

2026-10-05。五批评测体系已交付，用户随后授权完成[第一批输入/评分校准](agent-evaluation-alignment.md)。默认冻结数据为 `evals/aligned-v2`，原 `evals/current` v1 和报告保留。[第一批结果与溢出诊断](../reports/agent-alignment-batch1/README.md)记录全部失败，本批不修改提示词或检索算法、不新增付费调用；此前体系证据见[原实施报告](../reports/agent-evaluation-rebuild.md)。

## 评什么

| 层次 | 固定资产 | 主要问题 |
| --- | --- | --- |
| RAG | 三商家、六政策版本、54条规则、60条查询 | 能否找到必需条款，是否混入其他店/版本？ |
| Agent | 32案例、16配对 | 相同诉求换成不同事实，能否给出有依据的不同建议？ |
| Harness | 20检查 | 越权、假引用、过期事实、占用、预算及无进展是否被挡住？ |
| 上下文 | 8检查 | 事实、例外、版本、冲突、失败和原文能否保留/读回？ |
| 回放 | 5当前版本持久轨迹 | 能否离线重现调用和终态；缺记录/篡改是否报错？ |
| 人工复核 | 每次运行可生成逐例表 | 建议是否合理、解释是否编造、问题是否有用？ |

商家政策全部为专门编写的合成评测资料，尚未经过你或独立专家审查；不是商家真实制度。三店足以测当前权限/版本隔离，不能代表广泛商业场景。材料使用文字及人工核验记录，不测图像识别。

## 如何运行

在项目根目录 PowerShell 中运行。复用 `agent/.venv` 和锁定依赖；Docker 中本机 PG 要能连接，默认 `127.0.0.1:55433/agent_db`，可用 `RESOLVEFLOW_AGENT_DB` 指定。`validate/harness/replay/report/compare/rescore/review-*` 不需要业务服务启动；`rag/mock` 需要 PG，dense 还需要已配置的本地 embedding 缓存。没有模型或数据库时明确失败，不以零步骤通过或偷偷降级。

```powershell
.\eval.ps1                    # 校验冻结数据，不调用模型
.\eval.ps1 -Dataset evals/current # 显式校验历史v1
.\eval.ps1 -Mode harness      # 20 Harness + 8上下文检查
.\eval.ps1 -Mode rag          # 60查询，真实dense + BM25
.\eval.ps1 -Mode rag -Bm25Only # 显式只跑BM25，不宣称dense通过
.\eval.ps1 -Mode mock         # 32案例，脚本模型测试真实循环/工具接线
.\eval.ps1 -Mode replay       # 5轨迹严格离线回放
```

每次默认生成带时间的独立 JSON，位于 `reports/current-evaluation/`。可用 `-Split dev/test` 分组，`mock` 可用 `-Case A01A,A01B` 选案例，用 `-Output 路径` 明确报告名；已有报告拒绝覆写。相同名称再次运行会失败，应选择新名字。

`mock` 的模型为显式脚本，只能证明接线/失败路径，不能当 LLM 准确率。当前32例均因 `CONTEXT_REQUIRED_OVERFLOW` 未完成，运行返回1且保存全部案例；这是被测实现的失败，不是让执行器隐藏失败的理由。

退出码：0表示本命令完成且对应检查通过；Agent自动联合评分未全通过、Harness/回放失败、检索错误/越界或人审未完成/失败返回1；参数错误通常返回2。RAG的0只表示检索流程无错误/越界，覆盖率仍要读报告，不等于“召回100%”。

## 查看和对照

JSON保留实际发送的system/messages、输出限制、模型别名、显式动作、Observation/引用、usage、错误、预算和耗时。不是隐式思维链。每次调用开始前和返回后写报告；中断留下RUNNING/NOT_RUN和完整计划分母，不能当完成结果对照。摘要更适合直接阅读：

```powershell
.\eval.ps1 -Mode report -InputReport reports/current-evaluation/rag-final.json -Output tmp/rag-summary.md
.\eval.ps1 -Mode report -InputReport reports/current-evaluation/mock-scored-current.json -Output tmp/agent-summary.md
```

后续你决定修改被测实现时，用同样的manifest、案例选择、模型模式/参数重跑，然后：

```powershell
.\eval.ps1 -Mode compare -Baseline tmp/before.json -InputReport tmp/after.json -Output tmp/comparison.json
```

数据、模式、provider参数、评分代码、样本集合或分组不一致会拒绝比较；失败样本仍进入分母。文件包含改进/退化案例清单，单次小样本差异不是统计显著提升。本轮 `comparison-smoke.json` 是同报告自比，用于验证入口，结果0变化，不是优化效果。

评分器升级后不要覆写原始报告，也不要重新付费取响应。可对相同冻结数据的旧 Agent 请求/回答离线重判：

```powershell
.\eval.ps1 -Mode rescore -InputReport tmp/before.json -Output tmp/before-rescored.json
.\eval.ps1 -Mode rescore -InputReport tmp/after.json -Output tmp/after-rescored.json
```

重判保留执行时的代码和请求，只追加评分时间/代码hash及源报告hash。新模型调用为0。本轮的live-scored-current/mock-scored-current是这种评分器验证，没有再次调用真实模型。

## 分数含义与人审

Agent自动联合达标要求动作在允许集合、读取Gold要求的证据来源、退款引用完整且源/版本/hash匹配、必需条款来自实际检索。工具先后顺序不限。全转人工在明确应退款案例不算通过。v2 增加精确事实/主体/人工核验支持检查，质量场景允许订单送达事实替代重复物流查询，材料引用仍须实际读取；v1 的严格工具要求保留供历史重判。实际业务政策适用性、问题合理性与说明语义仍要复核。

RAG正例54、无适用条款负例6。覆盖@k是必需规则集合中被找到的比例；多依据查询可能只找到一半，全依据@5才是该查询所有必需规则都找齐。负例候选单列，不混入正例分母；拿到候选不等于可以退款。

生成某次 Agent 运行的待填写复核表：

```powershell
.\eval.ps1 -Mode review-template -InputReport reports/current-evaluation/live-scored-current.json -Output tmp/review.json
# 按逐例原始信息、政策和轨迹填写 reviewer/reviewed_at 与布尔判断；null表示尚未判断。
.\eval.ps1 -Mode review-score -InputReport reports/current-evaluation/live-scored-current.json -Review tmp/review.json -Output tmp/review-score.json
```

复核表绑定原报告hash，不能搬给另一次运行。ASK_CUSTOMER必须判断问题相关性，其他动作此项可留null。未填项、姓名/日期缺失、字符串代替布尔值、丢案例均不会伪装成人审完成。最终联合通过要求自动检查和人审都通过；填写者身份为声明，不是认证系统。本轮提供的表全部待复核，没有代替你打分。

数据Gold审查请先逐例对照 `evals/aligned-v2/agent/cases.json`、`gold/agent.json`，及 `rag/queries.json`、`gold/rag.json`、`policies/bundles.json`，记录不认可的条款/动作/来源要求。先发布有变更说明的新数据版本，再评测；不能看模型答案后偷偷修改原Gold。当前开发/测试按主场景家族隔离，测试集已经被脚本接线检查触达，应如实标记，不能声称未看过数据的盲测。

## 真实模型入口及数据隔离

本轮在你收敛为“只构建体系”之前已产生8个开发案例、21次真实DeepSeek调用；之后没有新增付费调用。已有记录作为当前失败基线保留，完整32例Live和测试集Live未运行。本节命令仅供以后你自行明确选择运行：

```powershell
.\eval.ps1 -Mode live -Split dev -Case A01A,A01B -LiveBudget tmp/evaluation-live-budget.json
```

读取用户环境变量 `Deepseek_API_KEY`，没有密钥就失败；不会切mock。必须显式选case及共享预算文件；每case最多6次、单次输出1024、共享文件最多96次传输，未知网络结果也占次数。共享文件有进程锁；崩溃遗留锁需先确认进程已停，不能删除预算来重置用量。还有USD0.50保守预留上限和输入/输出界限；预留按价格/字节估算，是本实验保险，不能当实际账单或账户总额限制。历史21次占用见本机已有共享预算文件。

运行创建随机 `eval_*` schema，正常退出清理，只向临时localhost合成源发GET。真实MCP/AgentScope/生产上下文与检索代码被复用；没有Java工单创建、审批、退款及业务回调。v2 首轮注入 revision 绑定的 `review_context`，材料查询返回 Java 协议的引用列表；v1 仍是正文放在材料查询中的历史合成协议，不能混作当前业务输入。两版都不是完整 Java 业务链验收。上下文八检查使用简化测试system，不能说明真实生产prompt在所有场景都装得下。

处理历史 `reports/current-evaluation` 的 v1 Agent 报告时，`rescore` 必须加 `-Dataset evals/current`；处理本批报告使用默认 v2。输入协议与 Gold 改变后，两版分数不能用作算法提升对照。旧 v1 回放包的源码 manifest 与新代码不同，保留用于历史检视，当前运行使用默认 v2 的五个新包，不放宽 strict 校验。

旧H1、40条检索查询、过期5回放包共15文件已备份后移除，清单见 `reports/current-evaluation/cleanup.json`。日常商城政策、兼容fixture、业务数据库、历史报告和其他作者工作区改动保留。本轮不清空商品/账户/订单，也不为评测消费日常队列。
