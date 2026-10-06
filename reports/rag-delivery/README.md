# RAG语义验证、生产接入及Agent对照

2026-10-06完整批次，统一交付。当前工程核验已进入收口，真实Agent对照随后执行；最终状态只在tasks/todo.md顶部维护。

本批复用原文冻结、结构保留、66个无截断子块与29个冻结问题，不改Gold或排名。生产已经有ReferenceCatalog短引用，本次外部文档短包是独立实验：正文/必要上下文相同，只把重复来源证明留在可信账本。116组回查通过；前5项完整JSON相对去重但带完整元数据的实验包减少dense73.93%、BM2574.73%。这是实验包的开销，不是生产首轮/整个Agent token节省。

## 语义质量的证据与缺口

模型在不见排名/作者Gold的情况下，读取范围内完整来源，标出回答需要的原文块。固定DeepSeek Flash，真实请求、用量和拒绝响应均留存；最多一次格式/引用修正，不按题目改规则。22/29份判断通过协议/来源校验，7份失败保留。其中18题需要政策依据，4题需补充事实/无依据；前2项全部依据覆盖dense11/18、BM2513/18，前5项均18/18。见policy-semantic-coverage.json。这个结果不是人工Gold；同模型作评估员有相关偏差，小样本/FAQ并非真实买家日志。独立人审0，正式准确率仍null，不能宣称“检索完美”。

第一次SDK消息构造失败实际0请求，却误增29计数，已按请求记录更正并保留semantic-preflight-audit.json和原失败报告。v2实际29请求、5通过、24协议失败；另1次调试请求；v3实际50请求、21通过、8失败。最终把非决定性的uncertain字段改为可缺省null，mandatory类别/引用/三维评分不放宽；仅重验保存响应，22通过/7失败、无新增请求。合计80真实语义请求；v2失败中的24次用量未完整留存，不能捏造全批token总数。v3全50次用量保留。

## 生产接入

`PolicyIndex.build`自动使用真实encoder的子块构建能力；追加012迁移，完整父条款保留权威引用，子块只作检索。真实BGE/PG探针：1501 token条款→4子块，最大380，返回完整条款/尾部例外/hash；超长query拒绝。子块错位、文本/向量篡改、父引用变造或READY数量/指纹不一致均拒绝，不静默BM25降级。generation映射只捕获一次，重建后旧run仍用原代；旧代失效拒绝替换。多bundle身份绑定完整映射。新增变更没有政策修改/审批/退款权限。

原Docker因dockerInference套接字启动失败，自动审批拒绝强制结束/删除套接字；正常desktop stop也失败。为继续验证，按PostgreSQL官方提供的[Windows ZIP入口](https://www.postgresql.org/download/windows/)使用[EDB二进制](https://www.enterprisedb.com/download-postgresql-binaries)，临时本地16.15/127.0.0.1:55434/新agent_db。精确下载/hash见runtime-environment.json，仅本地SHA，未声称供应商checksum验证。原卷/业务数据未触碰，无全局安装或服务。本地首次BGE探针fsync开启；后续隔离测试关闭fsync/synchronous_commit以降低临时测试I/O，不验证断电持久性；SQL事务/逻辑恢复/fence仍为真实PG。没有部署到原Docker业务服务。

## 集中验证与中间失败

实际命令和模块在commands.json，报告固定不覆盖。最初扩大到整个历史agent/tests的运行中断，仅观察到8个失败，无完整统计/根因归类，不能说全项目通过。第一次相关集中回归785通过/15失败：14个旧回放源码不兼容，1个政策hash_mismatch诊断回归。另一次在代码/配置最终固定前开始的785/15保留。诊断回归已修复，原断言保留；当前重新记录rag-delivery-v13十四包并逐一strict MATCH。v11/v12是开发过程中真实保存的中间包，现源码不接受其manifest，不冒充当前回放。v13导出曾因并行隔离DDL目录扫描遇到relation OID消失而13通过/1错误，只顺序补录缺的1包；后续PG验证顺序执行，不修改旧迁移。

当前代码Ruff/diff通过；mypy仍16个既有诊断/9文件/75源码，无新增错误但全项目类型门禁未通过。Harness28/28；相关单元/索引集成及真实BGE探针已过。最终相关集中回归800 passed/0 failed/errors/skipped（137.12秒，1个既有AnyIO弃用警告），见tests-accepted.xml；与中间失败报告分开。Docker OS级strict隔离、Java整链/网页、日常run消费均未运行。

## 整体Agent对照（待本批写入实际结果）

历史32例基线可复用：开工时生产harness/policies/tools与旧报告所有记录hash一致，只有未加载进Agent的离线rag_probes变化，证据baseline-provenance.json。原31/32联合达标/31完成/1未完成，158真实请求、provider input273381/output18588。新32例沿用同输入/Gold/模型参数/12次配置/入口，不重复付费跑另一份before；新RAG工程路径是运行变量。业务读来自合成loopback HTTP/MCP，真实SDK/PG/BGE/LLM，不是Java端到端或真实客户流量。新建议会匿名X/Y逐份做事实、政策适用和动作理由一致性检查，不给未完成候选捏造评分，不宣称独立人审。
