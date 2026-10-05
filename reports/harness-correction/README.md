# Harness 纠错闭环验证（2026-10-05）

实施依据：[本批规格](../../docs/harness-correction-loop.md)。保持唯一 AgentScope 2.0.8 循环、只读权限、Java 审批/金额、原恢复 fence。没有 RAG 算法、依赖锁、政策、Gold、Java/网页业务修改。

## 最终结果

- 44 模块 **616 passed / 0 skipped**，包括模型传输、参数门禁、工具 catalog/真实 MCP、关键断言、最终回调、Context、隔离 PG 恢复/请求/fence及严格回放。命令和结果：[commands.json](commands.json)、[tests-final.txt](tests-final.txt)、[tests-final.xml](tests-final.xml)。这是当前版本工程回归，不能等同于真实 LLM 的建议准确率。
- 独立现有 Harness **28/28**：[harness.json](harness.json)。新增闭环失败测试在上述 pytest 中，没有修改冻结的 20+8 检查输入来冒充提升。
- 最终严格回放 **13/13**：[replay-final.json](replay-final.json)。新 [correction-v7](../../evals/replay/correction-v7/manifest.json) 保留六原路径、短引用、非 JSON 修正/耗尽、临时工具修正/耗尽、关键文字事实修正、坏工具数据人工交接。原 usage-v6 和更早包不覆盖。strict 缺工具/改请求/不兼容记录及网络拒绝仍为失败测试。
- v1/v2 冻结数据校验通过：[v1](validate-v1.json)、[v2](validate-v2.json)；manifest SHA256 与上批完全相同。没有重新生成输入或 Gold。
- 定点 Ruff 和 diff 检查通过；配置式 mypy **16 个既有错误 / 9 文件 / 72 源文件**，无本批新增诊断，全项目类型门禁未通过：[mypy-final-v2.txt](mypy-final-v2.txt)。
- [只读状态](read-only-state.json)：public 仍 4 COMPLETED / 15 model / 10 tool / 8 callback，无遗留 test/eval schema；原用量仍96、limit=null、historical_limit=96、历史预留$0.2855712。新收费调用0，预算记录没有清零。

## 可验证行为

1. 模型只返回说明文字时，原输出进入已有结果日志、usage 正常结算；给下一轮 FORMAT 反馈，不把文字猜成工具或退款动作。修正成功继续，第二次错误停止；不同错误类别不能各领一份新机会。
2. 五个 MCP 返回缺字段、错类型/枚举/日期/版本、浮点金额或主体不一致时，不生成可引用成功事实；身份/路径/revision/来源类型错误直接停止。合法的大材料截取仍明确标记，并保持 revision 绑定，不伪造完整材料。
3. 超时/连接中断产生持久错误 Observation；模型下一轮可以重读原主体、换来源或交接。两次连续临时失败后第三次同工具请求不会执行；NOT_FOUND 等非临时错误不盲重读。凭据、未知编程错误、恢复 fence 冲突不会被包装为可重试工具成功。
4. 真实 LOST 引用配“承运商确认签收”、虚构退款到账、实付元/分或订单/行金额混淆会被当前有限文字规则拒绝。summary 与 findings 都校验，同规则再用于最终 callback；普通人工建议、客户陈述、条件/否定语句有不误杀测试。**这是有限模式检查，任意自然语言改写及材料真实性不在其证明范围内。**
5. 非 JSON、语义拒绝和临时工具错误在保存前/后及工具保存后的崩溃窗口恢复，不给新的纠错机会、不重复调用已保存结果；no_progress 与终态回放记录一致。原 deadline/manifest/预算不重置。

## 本批发现并修正的失败

- 先失败测试16项全部失败；实施后通过。最初恢复中的错误 Observation 显式 null 不符合 core 协议，改为保存时省略 null，没有放宽协议。
- 语义错误保存后的恢复首次失败：PG JSONB 改变结果键顺序，P3“已在P2字段”提示随之变动。排序该提示后，原请求 hash 一致；没有绕过 hash 检查。
- 重试耗尽回放首次失败：导出器把已保存但被拒绝的 READ_TOOL 当执行，及终态 no_progress 未落库。导出复用读门禁、终态在原 fence 条件内记录该诊断，保持工具/callback/用量比较断言。
- 首轮集中回归 **37 failed / 554 passed / 12 deselected**：[记录](tests-initial.txt)。失败包括尚未更新的当前回放路径、旧通用测试无物流来源却声称承运商丢失、非 fence 测试传入 opaque spend、评测模拟接口缺 core 字段。已逐项修复接线/示例与生产兼容，不删除原断言；[补充回归](regression-fixes.txt)中 manifest 无截止日期的投影错误随后修正。
- 评测环境 manifest 现在按已有合成政策日期投影真实 core 形状；退款状态补足 merchant_id / line_paid_amount / currency，来自同一冻结合成订单。此为评测 HTTP 投影变化，非生产缺字段兜底；原输入/Gold不改，历史原始轨迹不改，不把不同投影的历史 Live 结果当同条件对照。
- 金额小数点被分句切开、正常大材料截取被误判 revision 缺失，在新失败测试后修正。修正前615项全过；最终新增大材料断言及当前代码集中616项全过。自建未提交回放草稿留在忽略 tmp，正式旧包不改。
- 最终Ruff第一次从根目录执行遗漏agent配置，报32项配置差异；随后显式 `--config agent/pyproject.toml` 定点检查通过，未为根配置调整生产代码。
- 诊断命令有一次未设置 PG DSN 导致专项跳过，设置 DSN 后7项恢复通过；一次 v1 路径误写 current-v1 失败，改用实际 evals/current 校验成功。没有把这些失败/跳过报为成功。

## 实际额外命令与未运行

以下全部离线，不调用外部模型：

```powershell
agent/.venv/Scripts/python.exe scripts/agent_eval.py harness --output reports/harness-correction/harness.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --output reports/harness-correction/replay-final.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py validate --output reports/harness-correction/validate-v2.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py validate --dataset evals/current --output reports/harness-correction/validate-v1.json
agent/.venv/Scripts/python.exe -m mypy agent/src/resolveflow --config-file agent/pyproject.toml
```

Golden 生成及 Ruff 的准确参数另存 commands.json。validate 子命令只输出stdout，曾传入的 --output 未生成文件，收尾重新运行并保存输出JSON，未将缺文件当已有证据。测试中的 LiveModelClient 使用注入 HTTP 响应，虽按 live transport 路径运行，**不是外部 DeepSeek 结果**。

未运行真实 DeepSeek/质量对照、RAG实验/专家盲审、Java全链/网页验收、生产服务重启/部署或历史队列消费。新调查在下次正常服务启动加载当前代码；旧 manifest 不静默更换。其他作者的四个历史脏文件、草图和日志保持未暂存。
