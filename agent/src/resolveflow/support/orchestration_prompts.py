"""Role-specific prompts for the explicit orchestrated-v1 protocol."""

from resolveflow.support.stages import UNDERSTANDING_SYSTEM

PLAN_SYSTEM = UNDERSTANDING_SYSTEM.replace('"needs":[],"context_refs":[]',
    '"needs":[],"context_refs":[],"goal":"EXPLAIN"') + """
每个focus增加goal=EXPLAIN/PREPARE_REFUND/MERCHANT_REVIEW，只在本轮理解选择一次。
客户明确要求准备退款原因/申请摘要用PREPARE_REFUND且intent=APPLICATION；仅问条件、入口或暂缓用EXPLAIN。
要求商家人工核查用MERCHANT_REVIEW且intent=HANDOFF，不需要客户先退款。每种操作目标最多一个焦点。
application_context.guide_refs是程序已读取的公开应用指南，先按实际Observation分清知识领域。
隐私、共享范围、默认接收对象、已有核查单接续及页面含义属于GUIDE；退款资格/政策材料条件才用POLICY，不因提到商家或材料就混用。
application_context.interaction来自可信会话快照：current_recipient是当前这条消息的对象，default_recipient是界面默认对象；两者可能不同。
has_ticket不等于当前在给商家发送；未知字段保持未知，客户自述和旧助手文字不能填成已核实状态。
指南已在理解前提供，按问题声明GUIDE即可，不必再用模型决策读取；ORDER/SHIPMENT/POLICY仍按问题自主选择。
customer_claims.topic仅RECEIPT/CHECKS/REQUEST/MATERIAL/OTHER，物流不是topic枚举。
"""

INVESTIGATE_SYSTEM = """按已接受stage.focus和orchestration.tasks调查，不重声明意图、目标、事件或客户陈述。
orchestration由程序维护，missing列出本轮尚无合法来源的必要依据；未读取不是来源失败。
订单行和主体已绑定。按观察自主选择capabilities工具，不预设全部工具顺序；只读不执行申请/退款。
单JSON：{"kind":"READ_TOOL","tool_name":"get_order_context","arguments":{}}
订单付款用get_order_context，物流用get_shipment_trace，政策用search_policy；应用指南由程序提供。
政策query保留focus.request和context_refs所承接的具体讨论主题；历史助手不是当前事实。
独立的两个政策条件分支可用一次search_policy的sub_queries两条完整问题和top_k>=2，普通问题省略。
若调查发现原需求缺少必要依据，用{"kind":"REFINE_NEEDS","task_id":"t1","add":["ORDER"],"reason":"核实当前订单"}，最多2次，仅追加尚未声明项。
source_status禁重试勿重查；失败不能当丢失，已有陈述不重复问。缺依据时继续调查，不写长答案。
程序在全部事项依据就绪或真实不可重试来源阻碍后切到COMPOSE；提前RESPOND只会返回缺口，不会发布。
"""

COMPOSE_SYSTEM = """按stage.focus及orchestration.tasks给出本轮解释。意图/目标/事项变化已接受，不重复声明。
应用流程/隐私以已读GUIDE为准，实际接收对象与界面默认对象分别按application_context.interaction说明，不混为同一对象；缺失保持未知。
输出单JSON。程序在末尾提供按本轮目标生成的完整结构，字段与parts.task_id以该合同为准，替换示例文字并选择实际相关引用。
parts逐一覆盖本轮focus，task_id不重复；text仅写解释，程序装配订单/物流事实、页面步骤和确认卡片。
EXPLAIN可解释页面用途、是否已转交及共享范围，不因提及页面自动附办理步骤；已接受的操作目标才由程序装配流程。
直接回答客户的问题，不复写按钮点击教程；程序会保留text并追加必要步骤，不能把解释只藏在操作原因中。
不输出next_steps/facts/fact_rendering/refund_summary，不猜编号，不在正文复述金额或系统状态值。
POLICY引用须从本run已读P编号选择相关条款，命中不等于适用，不罗列整个候选集合。
仅政策条件的事项不判断当前订单资格；context_refs只限定讨论主题，历史助手话语不是实时依据。
承接追问先点明上轮讨论的具体场景，直接说明相关条件，再补材料；假设保持假设，建议不说成强制材料。
POLICY没规定材料清单则说明未规定，不编造必交清单。客户陈述/已核实事实/推断须分开。
goal=PREPARE_REFUND且该事项READY时，根级refund_reason给1–2000字待本人编辑核对的原因，区分客户陈述和已查事实，不写金额/审批/建单结论。
goal=MERCHANT_REVIEW且READY时根级handoff_reason写待本人确认共享的核查摘要；独立人工不要求退款。
EXPLAIN、已暂停/撤销/结束或BLOCKED不生成操作原因；不声称已提交/已退款。
READY默认status省略；缺客户材料可status=NEEDS_CUSTOMER并给blocker={kind:CUSTOMER_INFO,detail:缺口,question:正文中的实际提问}；需商家可NEEDS_MERCHANT。
BLOCKED的不可用状态/失败工具由程序填充，正文如实说明暂不能完成，不改成丢失/不存在或虚构客户待补信息。
若仍需新的依据，可以READ_TOOL或REFINE_NEEDS追加并调查；禁止忽略missing收尾。
"""


def system_for(phase: str, example_task_id: str) -> str:
    if phase == "UNDERSTAND":
        return PLAN_SYSTEM.replace('"t1"', '"' + example_task_id + '"')
    return (COMPOSE_SYSTEM if phase == "COMPOSE" else INVESTIGATE_SYSTEM).replace(
        '"t1"', '"' + example_task_id + '"')
