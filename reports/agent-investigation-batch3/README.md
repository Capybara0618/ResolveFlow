# 第三批调查与终止结果

2026-10-05，用户批准本批及真实 DeepSeek 调用；[规格](../../docs/agent-investigation-batch3.md)。已完成动作表达、调查/终止说明、无效编号追问拦截、命名条款的来源门槛及恢复/回放工程验证。没有固定五工具路线、宽松解析错误输出、政策/Gold/RAG算法调整、业务退款或历史工单重算。

## 从真实失败落实的修改

1. 基线 A01A/B、A05A/B 四例均在调查前连续输出错误包装，0/4联合通过、8次调用。原精简协议没有可模仿的动作对象。现在普通文字说明与六个独立扁平 JSON 示例分开；query 在根部，理由用 reasoning，检索词用中文聚焦已知事实。仍严格拒绝 type/action_fields 包装，一次修复，修复和失败也计预算。
2. 模型曾索要已绑定订单号。SDK在客户问答回调前拒绝已绑定的六类身份字段，反馈后允许改为读取或人工交接；重复错误只修复一次，不用猜意图来悄悄改动作。自由文字换名称/语义重复问题仍需要后续评审，不能声称覆盖所有无效追问。
3. 模型曾把人工核验挂到订单引用、用订单 LOST 代替承运记录。已给现有 R-LOST/R-DMG 增加当前事实和材料登记门槛，SDK/最终回调复用。人工来源、当前 revision、目标关联、四字段身份、最新结果及承运/付款/占用可验证；这些检查不自动证明原文结论正确。不同政策的条件分开说明，商家审批不等于 MANUAL_REVIEW，具备条件可以建议 REFUND。
4. 沿用原预算/无进展规则：两次无新证据反馈，第三次重复在执行前停止；新页/新来源版本可以继续。没有修改主循环、资金授权或增加自动审批。context v8、verifier v4，新七条回放于 `evals/replay/investigation-v5`，旧已提交包保留。
5. Windows曾四次阻止评测 JSON 的原子替换。评测入口只对本地 PermissionError 最多重试4次（合计最多0.35秒等待），失败保留partial并明确报错；不重试模型或整个案例。长问答案例只显示实际召回条款的解释，保留事实、问答原文、条件/例外及原输入cap。

## 真实调用：成功、失败都保留

模型为 `deepseek-flash`，真实 HTTPS、JSON mode、temperature=0、thinking disabled，输出上限1024；官方映射/价格[于本日核对](https://api-docs.deepseek.com/quick_start/pricing/)。业务数据是冻结合成案例，通过真实 SDK/MCP/embedding 与隔离PG运行；不是 Java 实际购物/退款，也不是商业用户数据。

| 报告 | 联合正确/选择数 | 实际调用 | 意义 |
| --- | ---: | ---: | --- |
| [live-before](live-before.json) | 0/4 | 8 | 原版本输出包装错误 |
| [live-dev-candidate](live-dev-candidate.json) | 1/4 | 10 | 一未发货正例通过，其余仍协议错误 |
| [live-dev-render](live-dev-render.json) | 1/3 | 11 | 丢失建议动作正确但来源不足；一例修复后超限 |
| [live-dev-final（实际为中间候选）](live-dev-final.json) | 2/4 | 19 | 拦住缺来源；出现核验条件误套到未发货 |
| [live-dev-fixed](live-dev-fixed.json) | 1/2 | 9 | 未发货通过，丢失修复读承运后上下文超限/条款不足 |
| [live-test-final](live-test-final.json) | 3/3 | 14 | 签收配对/质量正例完成且依据检查通过 |
| [live-test-quality-negative](live-test-quality-negative.json) | 0/1（未完成） | 4 | 累计调用cap阻止第5轮，不能算通过或证明决策错误 |

收敛阶段实际选择四个测试案例，**3/4联合完成正确，1例预算中断**；不能只报告3/3来隐藏未完成项。[逐例调用/usage/终止/报告hash](live-audit.json)。本批新增75次请求，加此前21次共96/96；保守费用预留由$0.0610104到$0.2855712（本批增加$0.2245608），这不是供应商账单。原始 usage 为供应商 token，预留为字节估计，不混用。累计预算已用完，没有新建预算清零。

入库报告行尾统一为LF，文件hash按这些实际字节重新计算；实际消息、响应、usage、请求内部hash和政策/Gold不变。评测保存入口显式使用LF，避免Windows格式被差异门禁判为尾部空白。

最后三例成功后，工程收口仅去掉未召回条款的说明、修正局部变量类型冲突及本地文件保存；最终字节版本未再收费跑Live。原始报告记录各自实际 manifest/代码hash，不能称全部报告来自最后一个源码版本，或宣称最终版本32例真实全通过。

本次执行者的语义复核（非独立专家审查）：

| 案例 | 结果 | 实际取证及解释 |
| --- | --- | --- |
| A09A | 建议退款，5轮 | 材料/订单/政策/承运；引用人工确认与承运LOST，说明有效签收冲突例外 |
| A09B | 转人工，5轮 | 相同诉求但实际签收、人工INCONCLUSIVE；不把签收当客户确认，不退款也不拒绝，明确需核验签收人 |
| A13A | 建议退款，4轮 | 材料/订单/政策；订单送达+人工CONFIRMED，引用正确，不强制额外读物流；说明矛盾/未知/已有退款例外及商家审批 |
| A13B | 尚无终局 | 已读材料/订单/政策/物流，尚未建议退款；调用配额结束。质量缺证终止效率仍需下一轮真实复核 |

这些冻结资产已参与工程验证，不是完全盲测。Gold独立专家审查仍待完成，评测器自动联合分数不替代语义审查。本批发现英语检索词可能召回错条款、候选说明会稀释条件；中文查询改为调查动作提示，未调整检索算法。召回/排序问题留给第四批。

## 集中工程验证

| 检查 | 结果/证据 |
| --- | --- |
| Python 36个相关模块 | 442 passed、0 skipped；[JUnit](tests-final.xml)/[输出](tests-final.txt)/[完整命令](verification-commands.json) |
| 入库行尾/本地保存收口 | CLI及回放相关50 passed，与442重叠，不额外累计；首次漏传测试PG配置导致10项跳过，补配置后全部运行 |
| 32冻结案例脚本/真实SDK/MCP/隔离PG/embedding | 32/32，148调用，0禁止动作/异常/未完成；[报告](mock-verified.json)。只是工程验证，不是LLM质量 |
| 独立Harness | 28/28；[报告](harness-final.json) |
| 新strict回放 | 7/7；最终报告见 replay-verified.json；含被拦截编号追问的修复、短引用读取；旧包不覆盖 |
| 冻结v1/v2资产 | [两套校验](frozen-data-validation.json)通过；3商家/6bundle/32案例/60查询，Gold未改 |
| Ruff/差异/链接 | 本批定点代码与测试通过，收口精确暂存核查 |
| 全项目mypy | 69源码仍9文件16既有错误；[输出](mypy-final.txt)。新增局部变量命名的3项诊断已消除，全项目门禁仍失败 |
| 业务数据/临时schema | 收口只读记录见database-final.json；无日常run/模型/工具/回调变化，无遗留测试schema或预算锁 |

除命令清单外，根目录实际运行：

```powershell
.\eval.ps1 -Mode live -Split dev -Case A01A,A01B,A05A,A05B -Dataset evals/aligned-v2 -LiveBudget tmp/evaluation-live-budget.json -Output reports/agent-investigation-batch3/live-before.json
# 其余分组/案例/实际输出文件见上表及逐例原始报告；复用同一预算，不清零。
.\eval.ps1 -Mode mock -Dataset evals/aligned-v2 -Output reports/agent-investigation-batch3/mock-verified.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py harness --output reports/agent-investigation-batch3/harness-final.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --output reports/agent-investigation-batch3/replay-verified.json
```

回放生成使用原测试和 `RESOLVEFLOW_REPLAY_GOLDEN_DIR` / `RESOLVEFLOW_SHORT_REF_GOLDEN_DIR`，7 passed/10 deselected。本批未提交的中间包移到tmp保留，最终新目录重新导出；没有改旧已提交包。首轮动作边界8失败/5通过、来源模块20失败，随后实现并补充反例；格式校验先失败后Ruff整理。旧P0标题/历史窗口的字符串匹配因说明文本变化出现两项失败，通过保留标题/参数分隔修正，未删除断言。中间mock31/32、最终前一版27/32含4本地文件错误和1超限均保留；mock-verified最终全通过。曾对已有目录/已有报告重新导出被不可覆盖门禁阻止，改用本批新输出，没有放宽门禁。

未运行：最终字节版本付费复测/全量真实32例、独立专家人审、RAG算法新实验、Java整链、网页和worker部署。本批没有启动常驻收费调查或写业务回调；下次正式启动才加载新源码，旧run不会静默换manifest。下一批是RAG召回/排序，仍由用户指示；先保证正式测评调用配额，避免探索用尽后反例缺终局。

提交只包含本批实现/测试/文档/必要合成报告，原四个工程/verify/Commerce测试及历史图日志保留；普通commit/push和远端确认在收口回复提供。
