# 当前32例来源说明

CODEX_REVIEW，已见原结果；原自动成绩不改。PASS为当前保存来源支持，WARN为表达/动作说明欠缺；未完成不评分。

|案例|有效动作|动作理由|商家可读性|来源结论|
|---|---|---|---|---|
|A01A|REFUND|PASS|PASS|未发货、已付、FREE均来自订单；未发货规则与资金限制引用完整，REFUND建议符合当前事实。|
|A01B|MANUAL_REVIEW|PASS|WARN|订单已在途，首次REFUND被事实门禁拦截后真实模型ESCALATE；query引入语料不存在的七天无理由。最终安全但转交只有通用reason_code。|
|A02A|REFUND|PASS|PASS|重复购买是客户诉求，订单NOT_SHIPPED/FREE/32900分支持整行REFUND；不把命中的质量条款当适用依据。|
|A02B|MANUAL_REVIEW|PASS|WARN|订单缺履约字段，承运在途；query未发货只能作为待核查政策假设，首次错误REFUND被拦，最终ESCALATE。转交说明不具体。|
|A03A|REFUND|PASS|PASS|购买计划改变，订单明确未发货且无占用，引用未发货与资金规则，REFUND有依据。|
|A03B|MANUAL_REVIEW|PASS|PASS|订单和补读退款源都为RESERVED/32900分；初次错误REFUND被拦，最终MANUAL_REVIEW正确说明占用，不拒绝整个申请。|
|A04A|REFUND|PASS|PASS|买错颜色，订单已付/未发货/FREE；整行退款有未发货规则支持。|
|A04B|REQUEST_INFO|WARN|WARN|订单读取NOT_FOUND，不能证明发货状态。REQUEST_INFO要求商家履约记录而非客户可补材料，方向安全但责任主体不清，宜交商家核查。此例是Java前置边界探针。|
|A05A|REFUND|PASS|PASS|承运LOST与本案CONFIRMED核验、无有效签收一致；第一次引用缺口反馈后补正确引用，最终REFUND支持充分。|
|A05B|MANUAL_REVIEW|PASS|PASS|承运在途、核验INCONCLUSIVE，不足以确认丢失；MANUAL_REVIEW未将客户说没到当LOST。|
|A06A|REFUND|PASS|PASS|承运LOST和核验CONFIRMED支持丢失退款，主规则虽排第2仍完整送入上下文。|
|A06B|MANUAL_REVIEW|PASS|PASS|承运送达与客户未收到不一致、核验未知；签收人与说明待核查，MANUAL_REVIEW支持充分。|
|A07A|REFUND|PASS|PASS|丢失主规则排第3，仍完整可见；承运LOST/核验CONFIRMED/退款FREE支持最终退款，不是检索漏项。|
|A07B|REQUEST_INFO|WARN|WARN|在途/核验未知且订单RESERVED。REQUEST_INFO没提出结构化问题、missing_evidence为空，摘要漏占用且承运结论并非客户负责产生；动作安全但可操作性/说明不足。|
|A08A|REFUND|PASS|PASS|丢失规则在第1，承运LOST与核验CONFIRMED支持整行退款。|
|A08B|MANUAL_REVIEW|PASS|WARN|承运工具两次503，失败源引用被拦后最终ESCALATE；没有假定工具失败为丢失。交接只有通用原因，未概括哪一来源失败。|
|A09A|REFUND|PASS|PASS|原诉求有签收争议，人工已核验运输丢失且承运LOST，引用丢失规则支持退款。|
|A09B|MANUAL_REVIEW|PASS|PASS|客户称签收未收到、承运送达、核验INCONCLUSIVE；依据签收规则转人工，不假定客户实际收货。|
|A10A|REFUND|PASS|PASS|原非本人签收诉求，经人工核验丢失且承运LOST，无有效签收；按丢失规则退款，不按诉求名称机械路由。|
|A10B|MANUAL_REVIEW|PASS|PASS|INCONCLUSIVE明确位于输入ReviewSnapshot，工具外层返回对应版本/hash；摘要没有捏造核验，MANUAL_REVIEW正确。|
|A11A|REFUND|PASS|PASS|被别人签收的诉求，经CONFIRMED丢失核验及承运LOST支持按丢失规则退款。|
|A11B|MANUAL_REVIEW|PASS|PASS|保留家人也未收到的已有回答；核验未知/有效签收需要商家查签收人，不重复要求客户回答同项。|
|A12A|REFUND|PASS|PASS|query在订单读取前产生，但已读本案CONFIRMED材料；主规则LOST来自核验假设并由后续承运LOST确认，最终退款依据完整。|
|A12B|MANUAL_REVIEW|PASS|WARN|材料工具两次503且承运送达，最终ESCALATE；初始快照不代替有效工具引用。通用转交缺具体说明。|
|A13A|REFUND|PASS|PASS|送达＋本案人工CONFIRMED核验支持质量退款，资金无占用；规则和观察引用完整。|
|A13B|MANUAL_REVIEW|PASS|PASS|一次SEARCH_POLICY因多余type被拒绝，下一次合法检索返回质量条款；核验未知，最终MANUAL_REVIEW正确。不能把非法尝试算RAG失败。|
|A14A|REFUND|PASS|PASS|检索在订单读取前发生，但质量诉求/CONFIRMED核验已经可见，后补订单DELIVERED；最终退款依据完整。|
|A14B|REQUEST_INFO|PASS|PASS|送达但只有客户破损主张；REQUEST_INFO列出照片/视频及部位/包装照片，供商家核验，不把照片当质量已确认。|
|A15A|REFUND|PASS|PASS|首轮动作缺kind被修正；送达/CONFIRMED/FREE支持质量退款，未绕过引用门禁。|
|A15B|未完成|NOT_COMPLETED|NOT_COMPLETED|检索已返回完整质量/资金/材料规则。第5次PROPOSE的CONFLICT只有O1被拒；第6次仍PROPOSE，finding引用O4但evidence_refs仅O1/O2，再次被拒。轨迹ESCALATE为SDK适配器的停止信号，不是模型选择，最终无有效建议。|
|A16A|REFUND|PASS|PASS|送达、CONFIRMED核验、FREE与0退款支持质量REFUND；金额32900分无单位冲突。|
|A16B|MANUAL_REVIEW|PASS|WARN|核验未知、订单RESERVED，MANUAL_REVIEW安全；finding保留RESERVED但面向商家的summary只提无成功退款，遗漏已有占用，说明不完整。|
