# 契约校准评测 v3

从 aligned-v2 不可变分叉，parent/file hash 见 manifest.json。32案例/16配对/3商家/6政策版本不变；31普通合成案例，A04B 是越过 Java 正常入口的未支付草稿边界探针，并非线上可正常提交的售后。

- A03B/A07B/A16B：行退款槽和退款状态均为 RESERVED。UNKNOWN 是操作级状态，PENDING 是旧样本混写词，均不能当行槽枚举；五 MCP 没有操作级状态查询，模型只能判断存在占用，不能声称已知道具体扣款结果。
- 物流 SIGNED 校准为 core CarrierConclusion 的 DELIVERED；送达不等于客户本人收到，签收争议仍保留。
- A04B：未支付草稿无 order_line，三个订单行来源均404；不得伪造 paid_at/payment_version。Gold 必须看到订单 NOT_FOUND，再补证/转人工，无读即转人工不能算联合通过。
- `harness/malformed-v2.json` 保留16份原非法案例，生产工具校验必须继续拒绝。其他 Agent Gold 和全部政策/RAG输入/Gold不变，原v1/v2不改。

replay/golden 是 v2 校准血缘的原始复制，只校验文件身份，不能冒充当前源码回放。当前 strict 使用独立 `evals/replay/calibration-v9`。资料仍同作者合成、未独立人审，不作为真实用户分布或泛化准确率。
