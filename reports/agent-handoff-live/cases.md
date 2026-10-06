# 12例来源审查

Codex已核对全部实际轮次；NONBLIND合成资料，原Gold及报告保持。详细来源SHA见review.json。

|案例|事实|政策|动作理由|责任|可读性|来源与取舍|
|---|---|---|---|---|---|---|
|A01A|PASS|PASS|PASS|PASS|PASS|第1/2轮读取材料和订单，第3轮已召回未发货、资金及质量条款；第4轮REFUND准确对应已付/NOT_SHIPPED/FREE/32900分，未用在途桩覆盖订单履约。商家审批步骤清楚；正文仍有编码与分单位，不当作已实现简约UI。|
|A01B|PASS|WARN|PASS|PASS|WARN|第2/4轮订单和物流均在途，第5轮MANUAL_REVIEW安全，明确商家核验下一步；但summary把P2同时写成R-UNSHIPPED-001与R-INTRANSIT-001，实际P1/P2分别才对应两规则。query七天无理由主题不在语料，正文引入在途退货/拒收/入库，本系统不实现该流程，只能作为外部核查问题，不能当已提供的政策或执行动作。|
|A02B|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|第5轮文字承认履约缺失/在途却选择REFUND且missing_evidence非空，被MISSING_EVIDENCE_ON_REFUND及UNSHIPPED_FACTS_REQUIRED拦。第6轮再检索、第7轮补读资金状态，第8轮仍REFUND且缺未发货确认，修正耗尽；终态STOP/HARNESS、decision=null。实际第6轮模型输入含字段反馈；政策已返回，不能归因漏召回或12次预算耗尽。|
|A04B|PASS|PASS|PASS|PASS|PASS|第2轮订单NOT_FOUND，第3轮有效模型ESCALATE点名失败来源及付款/履约/资金未知，交商家核查，不向客户索要系统记录，不把读取失败当否定退款权。未检索政策，未声称已符合具体条款；输入本身为Java前置边界探针。|
|A05A|PASS|PASS|PASS|PASS|PASS|第1轮CONFIRMED丢失材料、第2轮付款/LOST/FREE、第4轮承运LOST一致；第3轮主丢失条款排名第2，第5轮正确引用P2 R-LOST-001建议整行32900分退款，条件与例外保留，商家审批清楚。|
|A07B|PASS|PASS|WARN|WARN|WARN|第2/4轮在途、RESERVED/32900分和INCONCLUSIVE，第5轮summary明确占用、商家核查及承运核验，较旧摘要具体。但REQUEST_INFO的missing_evidence全是承运结论/商家核验而非客户可补材料；非空结构通过不能证明责任正确。没有ASK_CUSTOMER或实际发题，仍应转商家核查，行动与文字责任不完全一致。|
|A08B|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|NOT_COMPLETED|第3轮承运读取503，已作为P1失败指导显示；第5轮MANUAL_REVIEW的finding引用失败O3（且未在evidence_refs），短引用扩展以ACTION_CITATION_INVALID拒绝。第6轮真实模型ESCALATE但附带finding仍引用O3，反馈未被采纳，终态STOP/HARNESS、decision=null。模型确实尝试转人工，不等于得到有效模型建议；无需检索政策也不能拿错误读取当可引用事实。|
|A12B|PASS|PASS|PASS|PASS|PASS|第1/4轮材料读取503，订单和承运DELIVERED；第5轮有效ESCALATE明确get_case_evidence不可用、签收人待核验，责任为商家查投递/收货人。INCONCLUSIVE来自首轮review_context快照，未伪称材料工具成功；无RAG，不支持声称具体政策已检索。全文仍只在评测/轨迹，FAILED网页回调不传summary。|
|A14B|PASS|WARN|PASS|PASS|PASS|第1/2/4轮仅客户破损陈述、已送达、FREE，第5轮REQUEST_INFO具体列出照片/整体/包装，责任为客户提供、商家核验，没有自动发题。第3轮query添加无来源的生鲜，前三为未发货/资金/家居材料，未召回通用质量R-DMG-001；主张核验成立即可全额退款缺完整质量条款支持，且家居材料条款与订单electronics分类不一致。自动补证评分未检此语义边界，记录为警告不改Gold。|
|A15B|PASS|WARN|PASS|PASS|WARN|第1轮核验REFUTED但其他理由待调查，第2轮质量/资金条款、第3/4轮DELIVERED/FREE，最终MANUAL_REVIEW未否定整个申请。没有自然出现旧CONFLICT/缺引用错误，不能把完成归为具体纠错反馈收益。末句将其他理由属实统一归到R-DMG-001过宽，其他理由应按相应政策；摘要长且技术词多。|
|A16A|PASS|PASS|PASS|PASS|PASS|第1轮CONFIRMED质量核验、第3轮DELIVERED/FREE/无退款，第2轮完整质量/资金规则，最终REFUND符合整行实付32900分，审批责任明确，没有将客户陈述当核验。|
|A16B|PASS|WARN|WARN|WARN|WARN|第3/4轮均RESERVED/32900分，核验INCONCLUSIVE。summary已说明占用且归商家核查，但REQUEST_INFO的缺项仅为人工核验结论，不是客户材料；条件句核验成立且无其他退款记录仍没有明确原占用已结束，不能将无成功退款等同可再退款。最终未REFUND，资金拦截未被绕过；行动责任和条件表达需改善。|
