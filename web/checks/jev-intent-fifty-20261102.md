# Jev用途判断：旧Agent评测集50轮单次对照

2026-11-02，用户明确要求复用旧Agent评测集，补测原模型用途模块，每家各调用50次，不跑3轮或完整Agent。本轮仅评价已有候选事项的用途分类，不评价事项拆分、工具规划、RAG、最终回答或实际操作。

本轮已完成100次真实请求。固定Gold下原模型44/50、Jev42/50、组合44/50，组合误准备由1增至3；按实际缓存计数的模块费用估算低46%，token未减少。没有证据支持准确率提升或无损降本，详见下方完整分项和边界。

## 调用前固定

- 完整复用`evals/customer-workflow-comparison-v2/cases.json`的32场景/50轮，逐字保持原话、顺序，不按旧成绩选题。旧runtime只用于核对输入和提取此前客户原话，不拿旧87.5%任务成功率当本模块基线。原集来源可见、合成，非独立盲测；部分原话和之前30题小测有语义重叠，不称全新holdout。
- 输入为当前原话、同一会话此前CUSTOMER原话、预先固定的候选原句。历史助手回复、旧模型理解、事实异常、旧`expected_artifact`和本轮Gold不进入请求；两家语义信息相同。原操作模块只接受最多2个事项，本轮固定50批/62事项。混合的暂停/咨询或拒绝/准备分开判断；Q31保留拒绝退款与准备核查两个操作事项，是否另开单的旁支咨询不计入子项。候选由评测离线固定，不检验生产计划器是否漏提事项，也不把50轮称为生产50次实际触发。
- 五分类INFORMATION/PREPARE_REFUND/MERCHANT_REVIEW/DECLINED/UNCLEAR，标签和理由先写入`agent/tests/fixtures/jev-intent-fifty-v1.json`，由Codex标注，无独立人审。单纯“先不发送/提交”不能否定准备；暂停旧事项和新增咨询分开。Q23-T1同时询问认定质量并直接退款，能力咨询/准备请求有歧义，主标签预定UNCLEAR；预先声明另报排除此题的49条敏感性结果，但主分母始终50，不因结果调整标签。
- 固定当前原用途提示词与DeepSeek `deepseek-flash`，temperature=0、thinking disabled、JSON、max_tokens=1024；Jev固定`jev-1.14.0`、原Choice策略，不调提示/选项/阈值追分。主模型为供应商alias，记录实际返回model，不承诺固定权重。
- 一次执行，交替供应商先后，每条各一次，共50 Jev+50原模型=100 attempt硬上限；单家50上限，无自动重试/失败补跑，不覆盖既有结果。发送前保守预占总额不得超过1美元。失败留在分母；结果未知usage标未知，不填0费用。
- Jev任一事项confidence低于0.70或UNCLEAR整批回退；使用同轮已保存的原模型结果离线组合，不产生第三组新请求。分别公布原模型、Jev原始、组合成绩。回退费用是离线组合估算，不称正式生产三组付费运行。
- 主指标为50轮逐轮所有事项均正确；补充62事项准确数、把非操作误判为准备的次数、直接采用/回退数、错误清单及49题敏感性结果。费用/延迟仅该用途阶段；实际token分别报告，不跨tokenizer宣称统一token节约。

价格于执行前核对：[TypeSafe模型](https://docs.typesafe.ai/models)为Jev输入$0.042/M、输出免费；[DeepSeek价格](https://api-docs.deepseek.com/quick_start/pricing/)为Flash高峰cache miss输入$0.3/M、输出$1.2/M，低峰半价，cache hit另计。主要对照固定用高峰全cache miss保守估算，保留供应商原cache usage用于补充核查，不能称精确账单或实际降本。两家均有失败/估算usage时不得把缺失部分当零费用。

## 准备验证

首次先红为新执行器不存在；实现中一次括号语法错误已修，Ruff2个导入格式修正，mypy最初包路径缺失以`MYPYPATH=agent/src`解决，未加依赖。最终9新测试+29既有客户端/用途测试共38通过；Ruff2文件、定向mypy1执行器通过。新测试覆盖完整50输入/62事项、历史无未来、Gold不入请求、manifest修改拒绝、拒绝重跑、50/100上限、复合事项精确评分、未知费用不算0、模拟100次全回退且离线组合正确（mock非真实模型成绩）。

执行前只读接管确认f84d6b93已停止写入，main/origin一致，保留原四历史改动。首次暂存检查发现新fixture被Windows写成CRLF，已仅将本轮fixture规范为LF；标签/内容不变，差异检查随后通过。准备阶段无真实成绩，先提交准备/冻结manifest及源码副本，再显式`execute --live`发送一次。生产代码/.env/数据/服务不变，不调用业务接口或创建工单。

## 单轮真实结果

准备提交331bb36c已普通push并核实。随后冻结14份输入/源码/锁/历史来源，保存manifest及逐份源码副本到忽略目录`tmp/jev-intent-fifty-v1-20261102/frozen-source/`，执行一次。**50 Jev+50原模型，共100次请求全部COMPLETE，0接口/格式错误，0重试、0补跑**；真实返回模型分别为`jev-1.14.0`与`deepseek-flash`各50次，后者仍为alias，不推断其不可变权重。

主结论：**本轮未证明用途判断准确率提高，也没有token减少；组合费用估算较低，但非操作误判为准备操作的次数增加。** 不将此结果写成“Jev提高Agent准确率”或“同质量无损降本”。这是模块分类与离线回退组合，不是正式生产最终按钮/退款行为或全Agent对照。

| 指标 | 原模型 | Jev直接判断 | Jev＋预定回退 |
| --- | ---: | ---: | ---: |
| 50轮全部事项正确 | 44/50（88%） | 42/50（84%） | 44/50（88%） |
| 62事项正确 | 56/62（90.3%） | 54/62（87.1%） | 56/62（90.3%） |
| 非操作误判为准备（按事项） | 1 | 4 | 3 |
| 排除预先指定Q23歧义题的敏感性结果 | 44/49 | 42/49 | 44/49 |

Jev直接采用39/50（78%），回退11/50（22%）；直接采用中有2轮与固定Gold不符。回退为Q02-T1、Q09-T1、Q09-T2、Q10-T2、Q12-T1、Q13-T3、Q17-T1、Q18-T2、Q20-T1、Q28-T1、Q32-T1。没有按结果提高门限、改变提示词、改Gold或再跑一次。

| 事项类别 | 固定数量 | 原模型正确 | Jev直接正确 | 组合正确 |
| --- | ---: | ---: | ---: | ---: |
| 咨询INFORMATION | 29 | 27 | 24 | 26 |
| 暂缓DECLINED | 15 | 13 | 14 | 13 |
| 商家核查MERCHANT_REVIEW | 10 | 9 | 10 | 10 |
| 退款准备PREPARE_REFUND | 7 | 7 | 6 | 7 |
| 不明确UNCLEAR | 1 | 0 | 0 | 0 |

### 收益与退化逐条保留

- Q31-T1：“耳机转轴松了；我不要退款，想先看核查摘要，也想知道补充后是不是另开一单。”原模型把核查摘要选为咨询，Jev按冻结两个事项正确选DECLINED/MERCHANT_REVIEW，confidence .76/.81，组合修正一轮。这与此前30题的M03语义重叠，不是新的独立泛化证据。
- Q13-T1：“耳机签收可我没收到，请核对一下。”Gold为查证咨询，原模型正确；Jev选商家核查、confidence .85而被直接采用，组合新增一轮错误。原话没有明确要求给商家整理/安排核查，不能凭签收争议自动升级操作用途。
- Q23-T1：“耳机可能坏了，你能确定是质量问题并直接帮我退款吗？”预定Gold UNCLEAR，原模型选INFORMATION，Jev选PREPARE_REFUND、confidence .74且采用。两家均不符主标签，但组合由非操作错误变成准备操作错误，所以只看总正确数会隐藏错误严重程度差异。按预先规则另报49题，主结果不删除此题，也不因争议称其为客观安全违规；最终提交仍由本人确认。
- Q09-T2（纠正后“继续”）两家均UNCLEAR而Gold INFORMATION；该类仅陈述/继续的用途边界可能有合理不同解释，按先定标签计分，不事后改标签。
- Q13-T3（“继续查签收争议”）两家均MERCHANT_REVIEW而Gold INFORMATION；Jevconfidence .31触发回退，原模型仍错。
- Q18-T2的“不是人工说明”预标DECLINED，原模型为INFORMATION，Jev为PREPARE_REFUND；后者confidence .52触发整批回退，组合仍不符该子项。INFORMATION与DECLINED都不允许准备，但本轮严格五分类会将二者区分，不把语义分类错都说成实际越权。
- Q32-T1关于“如果以后要退款……先别申请”的事项，Jev正确选DECLINED、confidence .50，整批回退后原模型INFORMATION的错误被保留。该例证明回退既可能保护正确判断，也可能丢掉Jev正确的低confidence判断。
- Q09-T1、Q12-T1为陈述型输入，Jev选UNCLEAR，回退到原模型INFORMATION后正确；Q20-T1要求写申请原因，Jev选UNCLEAR、confidence .34，回退到原模型PREPARE_REFUND后正确。以上共覆盖所有两家/组合不符Gold的10轮，无隐藏失败。

### 用量、缓存与费用

| 项目 | 原模型50次 | Jev50次 | 组合（离线重建） |
| --- | ---: | ---: | ---: |
| 输入token | 28,254 | 70,301 | 76,515 |
| 输出token | 3,705 | 4,356 | 5,157 |
| 模型请求数 | 50 | 50 | 61（50 Jev＋11回退） |
| 高峰全cache miss估算USD | 0.012922200 | 0.002952642 | 0.005778042 |
| 按供应商实际cache计数、高峰单价估算USD | 0.009159000 | 0.002952642 | 0.004950138 |

原模型返回cache hit输入12,800、cache miss输入15,454，每条均核对与prompt_tokens合计一致，所有usage非估算。带实际缓存计数的组合估算较原模型低**46.0%**；不计缓存的估算低55.3%，后者高估对照组费用，不能只选55.3%宣传。两家全部100次实验费用按实际缓存计数、高峰单价估算合计**$0.012111642**，与发送前保守预占$0.112201602区分。未查询实际账户扣款，费用不是发票或实扣账单；原始cache usage/发送时间及分项计算见[费用复核](jev-intent-fifty-costs-20261102.json)。请求时间为2026-11-02约06:45 UTC开始，统一高峰估算与本次时间窗相符，仍不承诺所有计费细节均已核账。

**token并未减少。** Jev和原模型的tokenizer、请求协议和价格不同；Jev Choice每事项包含完整政策/选项，其原始输入更多，组合又包含回退。这里只能说模块费用估算下降，不能写“节省46% token”。39次原主模型判断被替换，同时11次回退导致总调用由50变61，不把主模型请求减少78%说成所有模型请求减少78%。

模块调用中位耗时Jev484ms、原模型1062ms；按同轮原模型耗时顺序加回退后组合中位500ms、均值740ms，原模型均值1052.1ms。组合耗时为离线重建，受单轮网络/缓存/交替顺序影响，非浏览器或全Agent延迟。

## 复核、复现与边界

[逐项结果](jev-intent-fifty-results-20261102.json)包含原句、固定Gold、两家选择、Jev原始概率/usage、回退、全部分数与每个attempt文件hash；[费用复核](jev-intent-fifty-costs-20261102.json)绑定结果文件hash并保留50条主模型cache原计数。原始100次实际请求/响应及冻结manifest留忽略目录，不提交凭据。全部100请求体hash与实际保存body一致；原模型packet逐条等于冻结输入，Jev body逐条等于原构造器输出；14原件与归档hash核对，公开结果离线复算一致，预算预占合计一致且低于1美元。

实际命令（根目录，已有项目venv）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_jev_intent_fifty.py agent/tests/unit/test_jev_intent.py agent/tests/unit/test_jev.py -q --tb=short
$env:MYPYPATH='agent/src'
agent/.venv/Scripts/python.exe -m mypy --follow-imports=skip scripts/jev_intent_fifty.py
agent/.venv/Scripts/python.exe -m ruff check scripts/jev_intent_fifty.py agent/tests/unit/test_jev_intent_fifty.py
agent/.venv/Scripts/python.exe scripts/jev_intent_fifty.py freeze --directory tmp/jev-intent-fifty-v1-20261102
# 仅在进程环境注入已有主模型凭据；Jev凭据由白名单本地.env加载，均不写参数/日志。
agent/.venv/Scripts/python.exe scripts/jev_intent_fifty.py execute --directory tmp/jev-intent-fifty-v1-20261102 --live
agent/.venv/Scripts/python.exe scripts/jev_intent_fifty.py summary --directory tmp/jev-intent-fifty-v1-20261102 --output web/checks/jev-intent-fifty-results-20261102.json
```

报告只是当前一次来源可见合成样本，类别不均衡、只有1个UNCLEAR；标签由Codex预先制定，缺独立人审，49题敏感性不能弥补这一限制。旧多轮被投影为相同的此前客户原话，不包含历史助手建议或真实业务观察；不检验两家各自生成历史后的滚动效果。候选固定、纯咨询也强制送分类器，因此78%承接率不等于日常所有轮次省掉78%主模型。未改生产模型/阈值/.env/简历，未新增业务读写或重启服务；原四历史改动保持。后续若要改善误触发，应使用独立开发题再调整，不在这50题上反复追分后称盲测提升。
