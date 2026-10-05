# 评测记录

模式：live；数据：resolveflow-evaluation-v1；来源：合成；Gold未经独立人审。

代码：c9160d1ca68fe64be3f9e15fefa28f85b8ae0da2；数据清单hash：1a430eacd39d6f64b303e63bcfd2654f0b8686382191a968ff2a9869f649d359。

自动联合达标：0/8；动作匹配：4/8；未完成：3；调用：21。

脚本模型只测试接线；自动评分不代替提问相关性、解释可信度的人审。

provider准确usage：21/21次；输入25546、输出5421 tokens。未知计费不计为零。

完整配对：4；两成员均达标：0；单成员不计配对分。

终止原因：{"ACTION_REFUSED": 1, "COMPLETED": 5, "CONTEXT_REQUIRED_OVERFLOW": 1, "CROSS_SCOPE_CITATION": 1}

| 案例 | 分组 | 动作 | 联合达标 | 失败/缺口 |
| --- | --- | --- | --- | --- |
| A01A | dev | — | False | ACTION_REFUSED |
| A01B | dev | REQUEST_INFO | False | get_order_context |
| A02A | dev | REQUEST_INFO | False | get_order_context, R-UNSHIPPED-001 |
| A02B | dev | REQUEST_INFO | False | get_order_context |
| A05A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A05B | dev | REQUEST_INFO | False | get_order_context |
| A06A | dev | — | False | CROSS_SCOPE_CITATION |
| A06B | dev | MANUAL_REVIEW | False | get_order_context |

案例耗时：median 6563.36 ms，p95 7545.22 ms（含本机执行开销）。

逐轮显式动作、工具Observation、原始请求和usage见对应JSON；不保存隐式思维链。
