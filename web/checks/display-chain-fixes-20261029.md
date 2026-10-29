# 展示链两项修复（2026-10-29）

状态：调查端取证修复离线通过，退款结果程序表达和真实复验待完成。

用户授权修复上轮剩余的政策引用与模拟到账措辞，并继承针对本轮真实模型不另设次数上限的授权。原27请求报告、错答/失败、成功退款及旧run/manifest保留，不重算历史或重复付款退款。原4历史脏文件不动。

首步：调查PolicySearchBridge复用PolicyIndex.small_context，同商家/manifest/冻结generation内规则<=8且序列化<=8192 UTF-8 bytes时完整读取，明确COMPLETE_SMALL_SET；大集仍原dense/top_k，不自动启用融合或rerank。P2保留政策标题和完整原文，指导区别丢失/损坏/普通在途/签收，未命中不借无关条款支持结论。身份、预算、本地读取与引用hash门禁沿用。不是规则命中即适用，也不宣称有通用语义裁判。

新增真实PG隔离schema+实际AgentScope脚本模型检查先因缺retrieval_context失败。小集可完整读不再需要encoder，原encoder错配测试移到真实9条大集保持原拒绝检查；新增大集dense/top1边界，原字节保持。当前64项（政策执行/大小边界/冻结generation/主体hash、context及引用验证）通过，Ruff定向修正测试既有导入顺序后再检查。无provider请求或业务数据写入，测试schema按原fixture清理；本地原日志tmp/display-chain-fixes-20261029。


第二步：只读退款结果part采用presentation=REFUND_RESULT，模型选择该用途但不提供text/guidance。程序从本run ORDER.refund_application按当前Java状态生成结果、已退金额、必要下一步及模拟资金说明，金额仍用原grounding校验；普通问题保留模型text，同轮可分别回答，不按关键词覆盖整条消息。不允许准备/暂停事项借结果模式产生申请动作。NONE必须显式权威否定，来源缺失/失败拒绝结果模式；批准/执行中/UNKNOWN不当成功，成功缺金额不从实付填补。编译后仍原buyer-view-v1/AnswerParts/Java协议，内部presentation不进入业务写入口，service manifest纳入refund_result.py内容哈希，旧run不迁移。

13项新结果测试先9失败2已有拒绝边界通过，随后补独立商品问题及准备/暂停边界共13通过；初版准备边界夹具未核对请求，先在evidence not ready处停止，补原approve_requests后走到真实模式门禁，记录该夹具错误不弱化校验。客服590项全量通过、Ruff通过（新导入顺序与行宽已定向修正）。未改前端布局、Java、政策源/索引或原成功退款，接下来保留数据部署并对当前完成订单真实追问，调查取证另用真实模型+明确合成/保存事实的受控场景检查语义，不把合成事实试验冒充新业务退款。
