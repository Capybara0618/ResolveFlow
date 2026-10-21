# 客服 Agent 双组多轮真实评测 v2

2026-10-21。**本批业务验收未通过。**14 类/44 轮分别执行自主 Agent 与固定流程，共 88 轮、176 次实际 DeepSeek Flash 请求。两组均无可发布回答，直接原因是所有 176 个模型决策都缺少顶层 `kind`，一次纠错仍未修正。不能以此前 121 项工程测试通过宣称真实客服已可用，也不能据此比较自主调度或上下文记忆的业务收益。

[冻结协议](../../docs/customer-agent-eval-v2.md) / [53文件及权重清单](../../evals/customer-agent-eval-v2/manifest.json) / [完整真实轨迹](runtime-results.json) / [统计](summary.json) / [逐轮失败核对](failed-outcome-review.json) / [收口记录](completion.json)。准备提交为 d1139d9049a9f81bf8c77067952f34c70f3bbf57；未改生产源码、模型参数、Gold 或简历，未重新付费运行失败样本。

## 执行与结果

保留旧 readiness-v1 的 12 类/36 轮输入和条件，新增两类各 4 轮的插问、暂停、恢复、纠正、撤回。两组同模型、同种子历史和政策/事实/预算，按会话交替先后；各组只用自身实际前轮结果。失败后不编造助手回答，下一轮继续使用真实失败前缀，因此本批多数后续轮次也没有正常成功对话前缀。

真实执行：Python ASGI → SupportRuntime → 自主 AgentScope 或评测固定调度 → 实际模型/隔离 PG 调用账。订单/物流 HTTP 和会话状态为冻结合成快照，政策来自保留 PG 的实际 generation。没有启动 Java/浏览器业务或退款队列；不称真实用户、独立盲测或全栈体验成绩。

| 项目 | 自主 Agent | 固定流程 |
| --- | --- | --- |
| 完整会话 | 0/14 | 0/14 |
| 完整/部分/失败轮次 | 0 / 0 / 44 | 0 / 0 / 44 |
| 失败原因 | INVALID_DECISION 44 | INVALID_DECISION 44 |
| 实际模型请求 | 88 | 88 |
| provider 输入 / 输出 token | 146668 / 22118 | 152812 / 21255 |
| 业务工具 / 政策检索实际执行 | 0 / 0 | 0 / 0 |
| 失败停止接口 P50 / P95 | 3.420 / 4.459 秒 | 3.178 / 4.231 秒 |

模型请求均收到正常响应，provider 错误 0，usage 全部为 provider 报告。账本1540→1716，未重置、未增加累计消费拦截。原输出上限1024，最大实际输出593 tokens，当前不是输出截断。预热8.863秒单列。上表时间是两次无效决策后的**失败停止延迟**，不是成功回答速度；没有成功回答，不能报告用户回答 P95 或降本收益。

事先目标为自主组至少12/14会话、40/44轮完整，新增两组全部完成且无虚构业务动作；本批未达到。直接失败已经足够判定会话/轮次失败；逐项条件标记 NOT_SCORED_NO_ANSWER，不把无回答伪装成通过，也不假装已经做过有效回答的语义评分。审核为 Codex 源审与失败核对，不是独立人工 Gold。

## 已确认的问题与待验证根因

实际第一条输出采用了 `type: json_object`、tasks、dialogue_events 和嵌套 ANSWER 对象，但没有顶层 `kind`。Pydantic 在识别动作分支前即报 `union_tag_not_found`；纠错提示只说使用目录合法动作，没有给出缺少 `kind` 的字段级例子。全部176响应都缺该字段，业务工具尚未执行，RAG也没有被调用。

源码对照显示：上次为控制窗口而精简 SYSTEM，旧版明确的 `{"kind":"ANSWER",...}` 示例被改成“ANSWER字段text、citations…”，首轮又同时要求任务和对话变化标注。**直接失败原因已由轨迹确认；提示表达及示例删除是优先待验证的根因推断，未做单因素真实对照，不能声称已证明唯一原因。**模型返回仍有任务与事件字段，因此工程桩能走通不代表真实模型理解动作 ABI。

下一修复应集中在完整的顶层动作示例/明确 discriminator、缺少 kind 时的精确反馈，以及使用本批保存响应做回归。随后先另冻结小规模真实冒烟，确认模型能连续读工具和回答，再决定是否新版本整体验收。保持已有任务、原文记忆和权限机制，不通过放宽解析、自动补动作或删除断言制造通过。本轮止于评测和诊断，没有偷偷改提示词或追加收费调参。

## 独立 RAG 回归

由于88轮没有进入检索，本批端到端数据无法评价 RAG 依据覆盖。另在模型批次结束后，按[独立冻结](rag-regression-protocol.json)运行原生产 `retrieve_policy`、实际 BGE/只读 PG、原9条Query×3轮，共27次，**无新增聊天模型请求**。[完整结果](rag-pg-regression.json)保留实际排名和阶段耗时。

- 3条旧真实模型保存Query：必要依据 Top3/Top5 均3/3；6条合成口语Query：均5/6。三轮排名相同，不能将重复27次当作27道独立问题或新验收集。
- 原 P02“快递确认弄丢了，我想知道退款要满足什么条件”仍未召回主丢失规则，前三/前五都失败；不能称漏召回已经解决。
- 独立 CPU4计算线程/1 interop 进程首次7.128秒（含惰性加载），后26次 P50/P95为31.54/37.48ms。它没有应用预热，不与上面的8.863秒启动时间相加，也不当完整客服延迟。两项测量顺序执行，没有并行性能负载。
- 既有[60题资料/架构比较](../customer-rag-v5/README.md)是历史证据，本轮没有重跑CE、dense/BM25完整比较或改默认RRF；不把旧分数包装成本批提升。

这说明在当前固定Query回归上检索链路可运行，且有已知漏召回；它不能弥补客服动作协议不可执行的问题，也不能证明新的 Agent Query 生成有效。

## 工程、命令与数据保持

准备阶段先有缺模块收集错误1，接实现后夹具调用记录格式断言失败1（字符串预期与既有tuple记录不符），修正后相关10项通过；scripts首次5格式/noqa问题已修。集中22文件Python121通过、0失败/跳过，相关Ruff通过；53文件/权重本地和真实只读PG预检前后均通过。旧5项 readiness-v1 测试依赖旧hash，保持原样且不计入本批121，不宣称全仓绿。Starlette弃用警告与SDK无效决策警告保留。

```powershell
# 仓库根目录。密钥从已有用户环境读取，仅传给子进程，不写入文件/输出。
agent/.venv/Scripts/python.exe scripts/customer_agent_eval_v2.py --freeze
agent/.venv/Scripts/python.exe scripts/customer_agent_eval_v2.py --check --database --output tmp/customer-agent-eval-v2/preflight.json
agent/.venv/Scripts/python.exe scripts/customer_agent_eval_v2.py --execute --output reports/customer-agent-eval-v2/runtime-results.json
agent/.venv/Scripts/python.exe reports/customer-agent-eval-v2/summarize.py
agent/.venv/Scripts/python.exe scripts/customer_rag_pg_profile.py --output reports/customer-agent-eval-v2/rag-pg-regression.json
agent/.venv/Scripts/python.exe scripts/customer_agent_eval_v2.py --check --database --output tmp/customer-agent-eval-v2/postflight.json
```

输出独占创建，统计脚本遇到成功回答会拒绝套用无回答评分，要求另行语义审查。不要重跑上述真实执行来覆盖历史。完整轨迹含88个run和176个持久模型调用（仅合成业务/模型请求响应，无密钥或数据库快照）；失败记录全部导出后已清理本批自有schema。public11表全行hash前后与预检/上批相同，原四历史脏文件字节保持，旧Gold/原清单保持。最终关闭临时PG/保留卷和所有项目端口，具体核验见收口记录。
