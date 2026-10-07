# Agent固定调查对照：试跑记录

2026-10-07。正式口径见[执行计划](../../../docs/resume-quantification-plan.md)。固定组复用生产Harness上下文、预算、MCP工具、政策检索、引用校验和一次纠错，固定读取订单→物流→材料，模型生成政策query及终局；动态组使用唯一生产AgentScope循环。两组共用商城选中BM25重排和deepseek-flash，temperature0、thinking disabled、JSON、单次输出1024、模型最多12。

- [trial-v1](trial-v1.json)：原calibrated-v3输入，4家族各1例、两组共8调查、26实际请求，6完成。固定A01A发现纠错桥接bug：GateAwareClient把被拒终局转换为SDK拒绝探针，基线又当成新调查动作拒绝，未给予已允许的一次纠错。修复只解释该内部探针，未改变领域Verifier；反例单测新增后基线4项全部通过。动态A13A仍因finding来源未列入evidence_refs而失败。
- [trial-v2](trial-v2.json)：明确修复基线后，4家族各1例、两组共8调查、26实际请求，7完成。固定4完成，动态3完成/1引用纠错失败。没有为了消除A13A失败再改模型提示、答案或Verifier；试跑全部独立于正式128次。

试跑同时发现原合成默认物流与明确未发货订单矛盾。按Commerce CheckoutPayments真实初始投影（status=NOT_SHIPPED、carrier_conclusion=UNKNOWN），另建[business-v1](../../../evals/resume-quantification-v1/business-v1/manifest.json)：通用条件为明确NOT_SHIPPED、默认IN_TRANSIT/IN_TRANSIT、无事件、无读取错误，改变A01A/A02A/A03A/A03B/A04A共5例。订单/占用/材料/其他真实冲突和错误不改，Gold、政策、RAG及案例编号/配对/分组全部保留；原calibrated-v3字节不变。

`scripts/resume_agent_inputs.py`生成不可覆盖的新输入；2输入单测证明只改空合成默认、不修改父对象、保留实际事件冲突；现有validate确认32例/16对/60query及Java读取契约。复制replay文件仅历史校准谱系，本轮strict仍独立使用当前18包，未将旧包包装成新输入的回放测量。

真实请求沿tmp/evaluation-live-budget.json累计，不清零。初始813次，经两个试跑增52至865。原请求/usage/轨迹保留在JSON，无API凭据。试跑源码hash在各自报告code_hashes中，基线bug及输入变化分别说明，不能合并成同版本成绩。
