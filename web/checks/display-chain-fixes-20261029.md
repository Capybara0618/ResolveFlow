# 展示链两项修复（2026-10-29）

状态：调查端取证修复离线通过，退款结果程序表达和真实复验待完成。

用户授权修复上轮剩余的政策引用与模拟到账措辞，并继承针对本轮真实模型不另设次数上限的授权。原27请求报告、错答/失败、成功退款及旧run/manifest保留，不重算历史或重复付款退款。原4历史脏文件不动。

首步：调查PolicySearchBridge复用PolicyIndex.small_context，同商家/manifest/冻结generation内规则<=8且序列化<=8192 UTF-8 bytes时完整读取，明确COMPLETE_SMALL_SET；大集仍原dense/top_k，不自动启用融合或rerank。P2保留政策标题和完整原文，指导区别丢失/损坏/普通在途/签收，未命中不借无关条款支持结论。身份、预算、本地读取与引用hash门禁沿用。不是规则命中即适用，也不宣称有通用语义裁判。

新增真实PG隔离schema+实际AgentScope脚本模型检查先因缺retrieval_context失败。小集可完整读不再需要encoder，原encoder错配测试移到真实9条大集保持原拒绝检查；新增大集dense/top1边界，原字节保持。当前64项（政策执行/大小边界/冻结generation/主体hash、context及引用验证）通过，Ruff定向修正测试既有导入顺序后再检查。无provider请求或业务数据写入，测试schema按原fixture清理；本地原日志tmp/display-chain-fixes-20261029。
