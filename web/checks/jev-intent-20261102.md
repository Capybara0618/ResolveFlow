# Jev操作用途识别试验

2026-11-02。用户授权先比较，再将可用的Jev接入已有操作用途复核。当前目标是`CHECK_REQUEST`，不替代整套上下文理解、事项拆分、工具选择或授权。候选事项仍由现有Agent提出，Jev对各事项选择INFORMATION/PREPARE_REFUND/MERCHANT_REVIEW/DECLINED/UNCLEAR。

## 预先固定的验证

- 30条人工构造中文说法，32个事项标签，五种用途各6条主类别；10开发、20测试。两条同时包含拒绝与准备，分别判断。标签由Codex在推理前确定，没有独立人工或盲测标签，不称真实用户泛化准确率。
- 固定`jev-1.14.0`和当前`deepseek-flash`用途复核；相同用户原话/必要历史/待核对原句，不把计划器提出的目标、业务异常、Gold标签当意图证明。
- 在调用前固定confidence0.70门限；任一事项低于门限或UNCLEAR整批回退原模型，不部分放行。该阈值是保守初始工程选择，不解释为70%正确率，也不看测试成绩再调整。
- 每条分别调用两家一次，最多60供应商attempt，保守预占最多1美元，无自动网络重试、不追加重跑失败。有效回退结果由同输入保存的原模型结果离线组合，正式接线的真实回退随后另测。
- Jev原始类别、回退组合、原模型分开计分，开发/测试分开报告，统计误判为准备操作的情况；不把回退后的好成绩全归Jev。

实现准备：通用Choice批次解析复用原有官方HTTP客户端，保持回答核验的原接口；逐项覆盖/枚举/概率校验全部通过才接受。新`jev_intent.py`只转换用途，原句由程序复制、理由为明确模板，不伪造Jev生成的自由解释。原引用/事项/用户最终提交确认继续由Harness与Java控制。

准备阶段25定向单元通过（15原客户端、10新用途/fixture用例），Ruff首次导入格式已修；定向mypy首次三处字典键推断/Any边界/列表注解已修，最终6文件通过。准备提交09da32c5。官方依据：[Choice](https://docs.typesafe.ai/primitives/choice)、[Confidence](https://docs.typesafe.ai/confidence)。

## 一次真实调用的比较结果

冻结后仅执行一轮，60次供应商attempt全部完成，没有重试或补跑。逐条输入、预置标签、选择、confidence及统计见[机器结果](jev-intent-results-20261102.json)。原始响应与attempt留在忽略目录`tmp/jev-intent-v1-20261102/`；manifest中的七份源码/fixture已逐份按hash归档到该目录`frozen-source/`。正式接线随后修改了源码，不更改原manifest，不用新代码重跑本轮。

| 分组 | 现有模型 | Jev原始选择 | 按预定规则回退的组合 | 回退条数 |
| --- | --- | --- | --- | --- |
| 开发10条 | 10/10 | 10/10 | 10/10 | 3 |
| 测试20条 | 18/20 | 20/20 | 19/20 | 5 |
| 全部30条 | 28/30 | 30/30 | 29/30 | 8 |

按事项统计分别为30/32、32/32、31/32。22条可直接采用Jev，其中本轮没有采用后判错的条目；8条回退。测试分组在调用前划定，但同样由Codex构造并标注，**不是独立保密测试集**。这批证据支持可开关接入，不支持宣称真实用户100%准确或整个Agent质量提升。

- M03：“耳机转轴松了，我不要退款，想先看核查摘要。”原模型选仅咨询，Jev选商家核查、confidence .99，按原定标签修正一条用途判断。它只准备摘要，后续发送仍由本人确认。
- U04：“退款和商家核查都说过了，我要前面那个。”历史仍不足以消解指代，预置标签UNCLEAR。Jev选UNCLEAR、confidence .79，因此按规则回退；原模型选准备退款，组合仍错误。这说明**回退不能保证正确**，没有为抹掉此错误而改阈值或标签。
- 另七条回退为I02、I04、U01、U02、U03、U05、U06。没有删除歧义、拒绝、混合事项或低confidence样本。

30次Jev共输入36,189、输出2,258 token，调用中位609ms；原模型输入15,745、输出1,915，中位906ms。按本轮固定保守价格估算Jev $0.001519938、原模型 $0.0070215，比较实验合计约$0.00854，不是精确账单。按保存的8条原模型回退usage离线组合，用途判断阶段估算$0.003367938、比全走原模型约少52%；这不是正式全链账单，也不是整个Agent降本52%。回退顺序耗时离线组合均值855ms、原模型930ms，仅为这轮网络测量，不承诺延迟改善。主模型使用服务商alias，未宣称权重永久固定。

## 正式接入的边界

现有AgentScope循环先提出候选事项；仅在原来的`CHECK_REQUEST`阶段，由Jev对每个事项选择用途。输入只含本轮原话、必要历史、待核对原句，不传计划目标或业务异常作意图证据。程序复制原句并生成固定理由，后续事项覆盖、引用、目标冲突、授权和本人确认仍走原逻辑。五分类由Choice原语直接支持，无需拆成互相可能矛盾的多个是/否问题。

独立开关`RESOLVEFLOW_JEV_INTENT_ENABLED=1`，初始门限`RESOLVEFLOW_JEV_INTENT_MIN_CONFIDENCE=0.70`；未配置默认关闭。根目录忽略的`.env`供日常启动读取，显式进程配置优先。与原回答后audit-only开关相互独立。关闭用途开关即可恢复原判断路径。配置非法或开启但缺key时，在启动/替换进程前拒绝。

任一事项不确定、Jev超时、余额不足或响应无效时，整批回到原模型；两次调用都计入同一个预算与deadline。预算超限停止，不靠回退绕过限制。请求/实际响应/usage写入原受fence保护的调用账本，`kind=jev, position=step+1`区分用途，原回答审查保留position=1，不新增数据表或迁移。已保存结果恢复复用；STARTED但结果未知不重新发送Jev，保留预占再尝试受预算约束的原模型。旧fence不能发布草稿。新代码/开关写入manifest，旧未完成run不静默换配置。

验证分两层：本节比较为真实Jev与真实主模型的独立用途调用；运行时测试为真实AgentScope/SupportRuntime/隔离PG、mock供应商响应。未重启日常项目，未通过网页新建真实工单，未执行退款，也没有把前者称为整条客服链路质量验证。

## 工程验证与限制

新增运行时测试覆盖高confidence替换、低confidence/UNCLEAR/超时/HTTP402/无效响应回退、关闭开关、完整与中途恢复、未知结果不重发、manifest变化拒绝恢复、旧fence拒绝落库、实际输出超预算停止。首次8项在未接线时失败后实现通过，随后补至11项。启动前检查新增两项先失败后通过；新单元配置校验随本批加入。

首轮64项相关测试通过（含旧回答核验、调用持久化与流式恢复）。本轮Ruff新增/修改9文件通过，定向mypy四个生产文件通过；系统Python没有mypy的尝试失败，随后用项目虚拟环境通过，未增加依赖。既有engine完整导入类型检查基线问题未在本轮扩修，不宣称全仓类型检查通过。未跑全仓Java/前端、独立人审或大规模真实用户评测。

扩大97项为95通过、2失败：`test_support_orchestrated_runtime.py`中的`test_api_persists_raw_protocol_and_reconstructs_plan_guide_gaps_without_new_calls`与`test_http_stream_projects_only_ready_response_and_recovery_does_not_resend`返回INVALID_DECISION。将接线前HEAD的完整agent树归档到`tmp/jev-intent-baseline-20261102/`，显式PYTHONPATH确认导入归档源码后，独立复跑同文件得到1通过/同2失败，不删改旧断言。XML保留为`final-tests.xml`与`baseline-orchestrated-tests.xml`。

进一步补测实际输入超限：先出现1失败，随后在结算实际usage后检查单步/旧run累计输入限额，超限保存STOPPED且不发布草稿；与输出超限共两例，运行时用例总12。最终相关95项全部通过、无skip，含本次新运行时、旧audit、存储/流式恢复、客户端/用途/启动、原用途与编排单元；新XML为`focused-final-tests.xml`。唯一警告为旧AnyIO别名弃用。离线复算公开JSON一致、七份原hash一致、60attempt分母一致，本机`.env`已开启用途开关并只输出无密钥配置确认；不重启已有业务进程。

实际命令（根目录，隔离PG55439）：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55439/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_jev_intent_runtime.py agent/tests/integration/test_jev_runtime.py agent/tests/integration/test_support_store.py agent/tests/integration/test_support_stream_runtime.py agent/tests/unit/test_jev.py agent/tests/unit/test_jev_intent.py agent/tests/unit/test_jev_launcher.py agent/tests/unit/test_support_request_check.py agent/tests/unit/test_support_orchestrated_engine.py -q --tb=short --junitxml=tmp/jev-intent-v1-20261102/focused-final-tests.xml
agent/.venv/Scripts/python.exe -m ruff check agent/src/resolveflow/support/jev.py agent/src/resolveflow/support/jev_intent.py agent/src/resolveflow/support/jev_intent_route.py agent/src/resolveflow/support/engine.py agent/src/resolveflow/support/service.py agent/tests/unit/test_jev_intent.py agent/tests/integration/test_jev_intent_runtime.py agent/tests/unit/test_jev_launcher.py scripts/project_runtime.py
agent/.venv/Scripts/python.exe -m mypy --follow-imports=skip agent/src/resolveflow/support/jev.py agent/src/resolveflow/support/jev_intent.py agent/src/resolveflow/support/jev_intent_route.py agent/src/resolveflow/support/service.py
```
