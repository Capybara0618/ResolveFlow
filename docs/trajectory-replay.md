# 严格轨迹回放 · v1.2核心

仅实现strict离线回放选定完整合成案例。counterfactual-recorded、counterfactual-world及新策略分支覆盖平台退出核心，不在C10验收。

## 1. 范围

运行记录包含run input、不可变manifest、实际ContextPacket、显式模型响应、工具参数/Observation、usage与终止原因。使用现有记录表导出ReplayPack，不强制完整session_event体系或事件溯源。

pack包括文件hash清单、source_run_id、schema版本、scope及版本、逻辑step/call顺序、实验Clock。只导出合成资料；不带JWT、API key、审批凭证。export只读、不覆盖旧包。

## 2. 可证明与不可证明

模型响应与工具结果都来自原记录。回放运行相同Harness逻辑，比较规范化动作、引用、预算和结束状态，定位首个分歧。不同trace ID/当前机器时钟不作语义差异。

这证明选定记录可复现，不证明新模型/Prompt会作同样决策，也不是再执行业务。核心只支持同manifest和已声明的schema版本；不兼容明确拒绝，不提供通用迁移。

默认只对完整顺序工具轨迹验收；并行批次或包含未知外部响应等未支持类型可以UNSUPPORTED_RECORD拒绝且报告，不宣称覆盖所有运行。正常运行仍可并行工具。至少保留5个覆盖不同终止方式的完整包。

## 3. 匹配与隔离

按逻辑step/call、工具名、规范参数、scope/version匹配；缺文件/hash冲突/调用不符即REPLAY_MISS或PACK_INVALID停止，不拿空值/相似结果/模型生成内容补齐。时钟和usage取记录；缺必需预算记录不声称预算精确复现。

evaluation_run_id隔离存储；原run ID仅作为非授权数据匹配。不加载业务凭证，不连接原库、Java、MQ或模型endpoint；工具adapter只读pack，CallbackSink只写本地结果。

strict在禁网络进程/容器中运行，用内存或独立临时回放存储，不使用生产checkpointer连接。测试确实拦住网络和业务写入，不只检查配置布尔值。

## 4. 验收与报告

C10实现导出、strict命令、5个golden packs及缺记录/篡改/写入企图反例。报告包含manifest、支持范围、完整/损坏/不支持数量、规范终局是否一致、首个不同step。缺包不能从分母消失。

成果写“对选定完整轨迹实现严格离线回放与回归定位”，不写“任意历史任务复现”“反事实评测平台”。新Prompt比较由冻结案例集重新运行完成，与严格回放分开。
