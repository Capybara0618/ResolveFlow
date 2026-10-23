# 纠正记忆与发布稳定性：六轮真实验证

2026-10-23。按[方案](../../docs/customer-agent-correction-v1.md)和[冻结新表达](../../evals/customer-agent-correction-v1/scenarios.json)，一次执行三会话六轮。**六轮全部发布，逐项源审四轮完整、两轮部分。连续纠正与暂停恢复已在本批真实生效，操作入口仍有语义错误，不能称全部验收完成。** 未更新简历或重跑旧题刷分。

## 实现和根因

旧程序已支持REPLACE/RETRACT，但旧理解提示优先“默认追加”，纠正目标只列id/topic，独立信息又容易合为一段。程序能执行替代，不代表模型会正确提出替代。

本次把目标旧原句直接放在correction_targets，提示先逐项比较原文，分开可独立纠正的收货、不同代收人和不同地点排查；同一事实否定、更正、确定性变化明确REPLACE，撤回RETRACT，新事实APPEND。程序继续校验同主题、更早、有效旧陈述和确切当前引文，保留旧原文及替代关系，不按关键词猜语义或仅按同主题覆盖。没有新增模型调用阶段、工具路径或多Agent。历史混合陈述不后台回写拆分。

这是一项上下文呈现和提示的定向改进，未做相同问题上的随机重复消融，不把差异全部归因为某一提示句。旧历史报告、原始输入和失败保持。

## 本批真实结果

| 轮次 | 行为 | 发布/源审 | 实际请求与工具 |
| --- | --- | --- | --- |
| C01-1 | 耳机未收到、家人没代收、门卫已问过 | 发布/完整 | 3模型，物流 |
| C01-2 | 暂停运输问题，插问正式退款入口 | 发布/完整 | 3模型，指南 |
| C01-3 | 恢复原问题，家人改为尚未确认，门卫事实不变 | 发布/部分 | 4模型，物流+指南 |
| C01-4 | 再确认家人无人代收，请商家核实、不退款 | 发布/部分 | 4模型，物流+指南 |
| C02-1 | 物流与丢失政策条件混合问题 | 发布/完整 | 5模型，物流+政策+指南 |
| C03-1 | 不退款的人工咨询与共享预览 | 发布/完整 | 3模型，指南 |

完整问答、陈述状态和事项见[实际对话](conversations.md)；[原始请求/响应/调用账](runtime-results.json)、[源审](review.json)、[统计](statistics.json)和[离线诊断](diagnostic.json)分别保存。源审为Codex逐条对照，非独立人工Gold或留出评测。原始文件SHA256：`1c17ec911247b6f362da70189b71e719ef9f8480f9a417e239626a478b408ae4`。

### 纠正与事项确实生效的证据

首轮三项分别保存，原家人陈述`c_4f2fdfd38a730b8f54cf6423`与门卫陈述`c_8a00d31474d3b53b7b7b3d56`独立。第三轮真实输出REPLACE家人旧id，旧陈述SUPERSEDED；第四轮又REPLACE第三轮不确定陈述`c_cfaf1c3d3cd9a505b948b8eb`。两个目标均为实际先前状态，程序没有代模型选择或改写响应。原“我没收到”和原门卫排查保持有效，没有被同主题替代误删；原句位置分别保留。

运输事项一直是t1，第一轮OPEN→第二轮PAUSED→第三轮OPEN；插问为独立t2。恢复后没有重复问门卫，正确采用“家人尚未确认”，随后改成“已确认无人代收”。第三、四轮未再发生facts没有占位符或漏本轮指南的发布失败；但本批没有自然触发修复反馈，不能声称联合反馈在真实错误下也已验证。

门卫反复确认还形成跨消息同义条目，第四轮替代最新重复条后原始同义条仍ACTIVE。当前未做语义去重，长期容量/任意主题纠正/旧混合陈述细粒度替代仍不由这两次成功证明。

### 仍部分通过的原因

C01第三、四轮均读取并引用正确的本轮指南，但答复把“请商家核查”放在“我的售后”。正确核查入口是“售后咨询”，“我的售后”用于正式退款。前一轮刚回答正式退款入口，后两轮把历史措辞带入了人工核查说明。

指南中正确内容已实际送给模型，离线原决定复算仍能发布且答复/记忆逐字相同；因此不是本次没取到指南，也不是再加政策召回即可解决。当前Harness主要检查来源类型/引用和状态，不证明自由文本步骤符合页面。根因集中在**回答组织时的操作语义混合**，与本批已修正的陈述替代是不同问题。

离线诊断只刷新过期deadline副本，原模型决定、指南和答复保持，不访问网络或业务写接口，不算新的成功生成。没有用正则把答案改成正确路径，也没有在这六轮之后继续改提示付费重跑。下一优先项应将稳定的页面操作信息明确区分/结构化呈现，必要时由程序渲染操作说明，验证多意图切换时不会串用入口；无需据此全面重构或加多Agent。

## RAG与实际效率

C02实际按需检索本店绑定版本，丢失条款为P1，保留“LOST且无有效签收记录、人工核验”的条件；没有把物流LOST当作订单付款状态，不要求无关具体金额。一次政策读取约90.743ms，仅说明本次预热后本地查询，不是RAG准确率或延迟SLA。个人原因退货语料缺口未在本批补齐，也未擅自改商家政策。

共22次真实模型请求、10次工具调用（6run/32调用账），无错误请求/反馈修复；Provider输入49797、输出2733，usage非estimated；Harness保守输入58770另计。usage账本1927→1949，未重置旧计数。预热28.525秒单列；六轮端到端各3.667–8.121秒，总33.122秒，不含预热。不做商用并发、长期稳定性或降本结论。

## 实际验证、范围和保全

工程关键测试先1失败/14通过，目标引用实现后相关63通过；实际隔离PG接纳纠正→回答失败→保存恢复零调用→后续继承，并保留独立旧事实。准备新单元/隔离PG4通过。最终客服单元+新执行器+纠正/会话更新PG251通过（7.93秒），相关Ruff及两生产源码strict mypy通过；真实清单预检和权重hash通过。

真实模型为配置和返回标识`deepseek-flash`。模型自主理解和选工具，政策使用实际保留PG索引及本地BGE，运行/调用账在独立schema。Commerce/Case HTTP事实是原版本化合成快照；Java、网页、退款和共享接口未启动/调用，不代替上批真实网页链路验证。

原PG public11表全行hash前后相同；原四脏文件及两份旧真实raw共六文件hash保持，新清单/权重核验不变；六run/32调用已导出，自有schema清理。未清库、改物流、改资金/授权或重建政策。报告和诊断首lint捕获循环闭包引用，改为实例绑定tools后重复离线输出一致、Ruff通过。

命令（PowerShell，测试从agent目录执行）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_customer_claims.py tests/unit/test_support_memory.py tests/unit/test_support_staged.py tests/unit/test_support_context.py tests/unit/test_support_grounding.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_support_conversation_update.py tests/integration/test_support_staged_api.py tests/unit/test_support_customer_claims.py -q
# 仓库根目录；execute已经执行，不可再次运行覆盖结果
agent/.venv/Scripts/python.exe scripts/customer_agent_correction_v1.py --check --database
agent/.venv/Scripts/python.exe scripts/customer_agent_correction_diagnose_v1.py --output reports/customer-agent-correction-v1/diagnostic.json
```

当前目录需要沿用项目Python环境及测试目录可导入配置；诊断可设`PYTHONPATH=E:/Code/Agent+Backend/agent;E:/Code/Agent+Backend`。旧冻结readiness未重跑，Java/网页未重验，不称全仓测试通过。原业务服务在开工时已停，本批仅临时启动原PG，收尾停回并保留卷；服务状态和hash见[收口验证](validation.json)。
