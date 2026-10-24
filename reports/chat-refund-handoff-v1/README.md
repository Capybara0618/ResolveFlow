# 聊天退款核验衔接修复（2026-10-23）

按用户授权修复确认原因、正常待核验调查与状态展示，保留[原真实失败](../chat-refund-live-v1/README.md)。本轮新状态仅见tasks/todo顶部。

实际结论：H1–H3核验衔接已由[真实手动确认入口整链](live-v2/manual-continuation/README.md)验证通过，包括两次正常Agent调查、商家核验与329元模拟退款；[自动客服回答](live-v2/README.md)仍因事实标注格式未发布，不能称整个自动链路完成。

## H1 确认原因进入初始材料

SupportRefundService复用EvidenceRepository，仅新建Case时将最终确认原因原样登记为revision1的CUSTOMER_STATEMENT，来源绑定客户/会话/草稿、版本绑定会话输入版与草稿revision、hash覆盖文本和主体；无核验结果。与Case/run/确认关联/回执同事务，草稿编辑取消/已有单接续/重放不添加材料。沿原派发evidence_refs和review_context读取，无第二轮建单或初始revision2。

V32追加迁移只允许初始revision1为未核验客户陈述，人工核验仍在后续revision；历史迁移/记录保持。商家实际核验接口对CONFIRMED/REFUTED/INCONCLUSIVE均能引用该初始陈述、保留原文、创建revision2及新调查binding。

实际验证：JDK21，java目录`./mvnw.cmd -B -pl case-service -am -Dtest=SupportRefundApiTest,SupportRefundWireTest,EvidenceApiTest,ReviewedEvidenceApiTest,AgentRunDispatchApiTest -Dsurefire.failIfNoSpecifiedTests=false test`（PowerShell两个-D参数均整体加引号）。真实隔离MySQL/Flyway/HTTP：Case68通过（确认43、原材料8、人工核验9、派发8），shared DTO2通过，0跳过，reactor56.578秒。限定SupportRefund格式通过，git diff --check通过。

失败记录：最初Maven未整体引号导致-D参数被拆，不计测试；新两项红测均失败。初实现触发原revision>=2约束（40项4失败1错误），追加V32；之后测试异常分类预期不符（40项1失败），改为断言真实DataAccessException根因CHECK名字；扩测68项4失败为客户投影未暴露revision、旧多人fixture未领取，分别改DB断言及显式生产领取，再全组通过。不删既有断言、不修改旧迁移、不降低核验条件。额外一次补丁因格式化后上下文不匹配未写入，定位后修正。

本步未重启/迁移原项目、未写原业务库或调用Provider，原usage2076；四历史脏文件排除。后续H2调查上下文/纠错与有效人工复核建议，H3双端状态和集中链路确认。

## H2 正常待商家核验建议（2026-10-24）

原H1 3c92f0b已同步。按适用政策的上下文明确“客户陈述/人工核验/最终审批”三个概念；缺核验可用现有PROPOSE/MANUAL_REVIEW，保留已查事实、政策和商家下一步。SDK实际工具目录增加完整语法例子；INVESTIGATION_FACTS_REQUIRED反馈不再泛称SOURCE，而明确未读可查、已查缺关联CONFIRMED可人工复核、不让客户补系统记录。原一次修正、REFUND检查及FAILED/ESCALATE语义不变，不把拒绝结果改标成功。

使用上次6条真实模型动作及原工具结果离线送入唯一AgentScope循环：原末条REFUND仍6调用后被拒；仅末条改为合法人工复核建议时，6调用/3业务读取、相同一次修正完成，最终worker verified_callback仍为PROPOSAL/MANUAL_REVIEW。记录不改、不联网；这不是新真实模型成功率。

验证：新定向4通过2.36秒；10个相关Harness/上下文/纠错/退款来源/契约模块195通过6.69秒；Ruff4文件、完整strict mypy3源码通过。最初新夹具严格JSON枚举、generation_for、短编号目录未绑定及Mock字节估计溢出分别修正：使用model_validate_json/显式代际/正式reference_format/带原DeepSeek tokenizer的脚本模型，不扩大预算。原断言先红后绿。完整strict扫描较慢，另试follow-imports=skip产生4个SDK第三方基类/ignore诊断；完整扫描最终独立通过，以完整结果为准，无源码压制。Provider新增0，原usage2076，原项目/失败报告保持。

## H3a 客户进度投影（2026-10-24）

H2 d128c1c首次普通push遇schannel连接中断，ls-remote确认远端仍3c92f0b后普通重试成功并核实d128c1c，未强推。CustomerCaseService沿原result.message区分当前有效人工复核建议“等待商家核验申请情况”、当前调查失败“本次调查未完成，已转商家继续核查”、当前待审授权“退款方案已生成，等待商家审批”；其他PENDING_REVIEW为“等待商家复核”。只读取当前revision，旧建议/旧失败不冒充当前结果；消费者不新增协议字段、不暴露内部方案/失败原因。消费后执行失败、UNKNOWN和终态原投影保持。

新HTTP回归先红1项；实现后真实隔离MySQL/HTTP客户9+确认43共52项通过0跳过，reactor57.348秒，限定Customer格式/diff通过。一次格式命令regex含竖线被Windows wrapper解释，退出255未跑测试；改无竖线限定表达式后正常。原项目未重启、原数据/模型调用无新增，usage2076。后续H3b挂接卡片标题与商家核验入口、区分失败建议。

## H3b 双端状态与核验入口（2026-10-24）

H3a 79d391e已同步。客户卡片对PENDING_REVIEW使用Java投影的进度说明作标题，其他状态/UNKNOWN/完成判断保留。商家有效MANUAL_REVIEW显示“等待商家核验”，初始客户陈述未核验时提供“核验申请陈述”按钮，直接展开原材料与核验操作；点击只打开材料，不创建授权。当前revision实际AGENT_FAILED显示“本次调查未完成”，不再显示“等待调查建议”，旧失败不继承到新revision。核验后有效退款方案/当前授权就绪，仍沿原审批入口。

前端新增5红测→定向25通过；全34文件245项通过26.13秒，vue-tsc与Vite正式构建通过。覆盖核验前无批准、查看原陈述、授权就绪后审批、失败/旧版及客户三类标题。未添加依赖或改变审核条件。下一步正常启动当前版本、冻结一笔新合成订单的有限真实验收；旧失败/订单不重发或覆盖。

## 最终验收与边界（2026-10-24）

`accept_chat_refund_handoff_v2.py execute`保存7请求客服失败；`continue_chat_refund_handoff_v2.py`不发新客服消息，沿同单手动确认，10请求/两正常调查整链通过。首次MANUAL_REVIEW及核验后的REFUND均5模型、0修正。唯一模拟退款32900分SUCCEEDED，原客户会话和详情均CLOSED_SUCCESS。所有原数据/旧失败/索引/四历史脏文件及旧SHA保持，[审计](live-v2/final-audit.json)无待处理run、原账2093、总17请求含全部失败。普通status各服务全健康，项目保持运行。

当前未解决的是客服多事项回答的事实注释与自然正文一致性，不是本次材料核验或RAG漏召回；原候选严格拒绝、未伪造成功。没有重发失败题、修改旧Gold、放宽退款条件或测简历指标。本次只证明上述单合成样本，不是整体准确率。源码与记录按小步普通push同步，四旧脏文件不夹带。
