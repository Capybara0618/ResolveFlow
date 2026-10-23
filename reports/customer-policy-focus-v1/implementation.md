# 同一次检索的可选双分支（2026-10-23）

诊断bf85195已普通push核实。本小步只增加按需检索能力，模型何时拆分/如何生成Query在下一小步提示与场景验收中验证。

## 协议与执行

`READ_TOOL search_policy`和旧`SEARCH_POLICY`兼容原query/top_k；新增可选`sub_queries`，有值时必须恰好两条非空且去空白后不同，每条至多1000字符，top_k为2–5。query保留完整问题和原始意图；有子Query时只执行两条子Query，不再额外执行宽泛主Query。SDK工具schema、Pydantic、Engine和BoundSources同步，其他旧参数不变。

每条分支沿用正文dense+正文BM25+标题BM25/各最多5候选/正BM25过滤/RRF，固定商家/manifest/generation。最终先覆盖各非空分支的首候选（相同来源去重），其余位置按跨分支RRF补齐；不按规则ID、Gold、退款意图关键字或手写政策路由排序。第二分支失败整体返回来源失败，不发布第一分支的半份结果。空分支不补造条款。

这是一次Agent工具动作/一次local-read记账，内部至多6次索引搜索、2次本地query embedding，计时分branch记录。没有额外LLM、ReAct轮次或新服务；不是所有问题默认拆分。模型/工具权限、来源原文和金额职责不变。检索版本变为support-fields-branches-v2，相关代码已有manifest哈希覆盖；旧run不静默升级。

## 验证与实际结果

- 首关键红测5失败/23通过。PowerShell第一次用了不支持的花括号路径，命令未运行；改成显式路径后定向35通过。mypy首次profile重复定义1错误，改branch_profile后通过。
- 扩大客服单元首轮1失败/317通过：加长capabilities说明使旧Mock保守字节计数的修复包溢出。保留原预算/断言，删除重复目录说明（参数在SDK schema，使用方法由staged提示负责），后定向41通过。
- 最终客服单元+真实AgentScope/隔离PG的staged API/流式runtime共 **322通过，0跳过（8.82秒）**；5源码strict mypy、相关Ruff通过。原Starlette弃用提示保留。
- 新增PG测试的Ruff首轮1处长行，换行后通过，未修改测试行为。
- 实际SDK验证理解→双分支单工具→回答仍3模型调用；PG保存完整query/sub_queries/top_k，模拟已保存run恢复后 **0新模型/0新检索**，原权限凭证未持久到请求。
- [真实本地索引确认](branches.json)：默认7条Query的前五排序与冻结结果完全一致；分支Query取自原冻结诊断中的语境/假设两个变体，当前前3为普通在途/承运商丢失/损坏，所需两条均覆盖，原文hash一致。单次热双分支73.46ms、预热单列，不作为稳定延迟或统计提升；这些Query是人工诊断输入，不代表模型已会自动正确生成。
- 确认经生产BoundSources→PolicyIndex，generation沿用原run；全部public表hash保持，无HTTP/生成模型请求。原宽泛单Query仍保留原排序，未改旧报告、政策原文/索引、Gold或日常run。Java/Web未启动，PG保持供接续验证，usage2022。

入口：`scripts/check_policy_branches_v1.py`拒绝覆盖原确认；命令与源码SHA在原JSON。下一步补理解/Query保留语境和条件、回答只讲相关条件与缺失材料，真实自动选择与最终回答质量尚未复测。
