"""Author source-aware synthetic evaluation inputs; no model, network or business writes."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals/customer-quantification-v1"


def write(name, payload):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def turn(text, criteria, sources=(), artifact="NONE"):
    return {"text": text, "criteria": criteria, "required_sources": list(sources), "artifact": artifact}


def agent_cases():
    cases = []

    def add(family, snapshot, *turns):
        cases.append({"id": f"Q{len(cases)+1:02}", "family": family, "complex": family != "ordinary",
                      "snapshot_id": snapshot, "turns": list(turns)})

    add("ordinary", "P01", turn("我这副耳机现在送到哪里了？先查物流就好。", ["使用当前签收记录，不能等同本人已收到", "无退款/人工摘要"], ["SHIPMENT"]))
    add("ordinary", "P02", turn("台灯运输有没有异常？帮我确认承运商记录。", ["当前LOST与客户陈述分开", "不自动申请退款"], ["SHIPMENT"]))
    add("ordinary", "G01", turn("请告诉我这件商品的实付金额，先不处理售后。", ["金额须订单当前来源，不能只引用商品展示", "无操作产物"], ["ORDER"]))
    add("ordinary", "G02", turn("如果只需要商家帮忙核查，也一定要填退款金额吗？", ["独立人工咨询不要求退款金额", "GUIDE不是政策资格"], ["GUIDE"]))
    add("ordinary", "G03", turn("给商家发核查材料之前，我能选哪些聊天记录给他看吗？", ["仅确认共享内容，不自动全历史", "无代发承诺"], ["GUIDE"]))
    add("ordinary", "G05", turn("我只想看给商家的说明草稿：耳机按键按了没反应。", ["故障为未经核验客户陈述", "人工摘要待确认、无退款产物"], ["GUIDE"], "HANDOFF"))
    add("ordinary", "P01", turn("假如签收记录存在，客户说没收到，店里的处理原则是什么？", ["签收争议人工核验及事实不足处理", "假设不认定本单资格"], ["POLICY"]))
    add("ordinary", "P02", turn("承运商已经判丢又没有有效签收时，本店退款有什么前提？", ["无有效签收且人工核验，整行全额", "政策不证明本单实际无签收"], ["POLICY"]))
    add("correction", "P01", turn("耳机没拿到，我已经问过门口代收点，说没有。", ["分开本人未收和代收点排查", "未核验标识"], ["SHIPMENT"]),
        turn("刚才讲错了，代收点还没开门，实际没有问到。请按这个情况继续。", ["旧已问过/没有失效，未询问有效", "不再以排除代收点为依据"], ["SHIPMENT"]))
    add("correction", "G05", turn("耳机右边完全不响，我想先整理核查说明。", ["人工草稿待确认，右边不响为客户陈述"], ["GUIDE"], "HANDOFF"),
        turn("改一下：左右都能响，是右边偶尔断断续续。重新整理，别发送。", ["完全不响失效，间歇异常有效", "摘要保留纠正与未经核验，不伪造事实"], ["GUIDE"], "HANDOFF"))
    add("correction", "P02", turn("台灯还没收到。请查物流，不准备申请。", ["LOST来自实际物流，未收为客户陈述"], ["SHIPMENT"]),
        turn("我仍然没有拿到，只是补充一句，不用办理。", ["保留补充陈述，不生成操作摘要"]),
        turn("物业送过来了，未收到这件事已经结束，不用再查。", ["所有本人未收同义陈述失效，找到有效", "事项结束，无操作产物"]))
    add("correction", "P01", turn("邻居说没有收，家里人还没有联系上，我自己没拿到。", ["分开邻居与家人状态", "不把未联系当无人代收"], ["SHIPMENT"]),
        turn("邻居刚说替我收了，家人依然没联系上；先别申请。", ["邻居否认失效，承认代收有效", "家人未联系独立陈述保留，不按RECEIPT全清空"]))
    add("interrupt_resume", "P01", turn("耳机签收可我没收到，请核对一下。", ["当前签收与客户主张分开"], ["SHIPMENT"]),
        turn("这件事暂缓，我先问：人工回复以后就会自动显示解决吗？", ["旧事项暂停，新问题有GUIDE", "回复不等于解决"], ["GUIDE"]),
        turn("回到刚才那笔耳机，继续查签收争议。", ["原事项恢复，不重复创建同一问题", "实际重新读当前物流，不复用旧run引用"], ["SHIPMENT"]))
    add("interrupt_resume", "G05", turn("帮我准备核查说明：耳机充电接口松动，先给我看。", ["核查草稿待确认"], ["GUIDE"], "HANDOFF"),
        turn("先暂停说明。用户换商品咨询会丢失之前记录吗？", ["旧事项暂停，无操作摘要", "每行独立记录且历史保留"], ["GUIDE"]),
        turn("继续整理刚才接口松动的核查说明，仍先不发。", ["恢复原事项和有效陈述", "人工摘要待确认"], ["GUIDE"], "HANDOFF"))
    add("interrupt_resume", "P02", turn("请先帮我准备台灯没收到的退款草稿。", ["订单/物流/政策与退款产物一致"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"),
        turn("草稿先放一放，怎么查看商家核查进度？", ["退款暂停，新GUIDE问题活跃，无退款摘要"], ["GUIDE"]),
        turn("现在接着准备台灯那份退款原因，我核对后再提交。", ["恢复原退款事项，最新有效陈述", "当前订单与物流及政策须重读"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"))
    add("interrupt_resume", "P01", turn("查一下耳机签收记录，我没收到。", ["读取当前物流"], ["SHIPMENT"]),
        turn("先不查签收了，我问一下一直运输中是不是就能按丢失退款？", ["旧调查暂停，政策假设独立", "IN_TRANSIT不等于LOST，不判断当前资格"], ["POLICY"]),
        turn("还是回到耳机签收的事，给我退款原因草稿，先不提交。", ["原问题恢复可更新APPLICATION", "不能继承假设在途为当前事实"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"))
    add("goal_switch", "P02", turn("台灯没收到，请准备退款原因供核对。", ["退款草稿/LOST处理前提"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"),
        turn("我改成只让商家调查，先别准备退款，帮我写核查说明。", ["人工而非退款摘要，旧退款停止", "有效未收陈述保留，未发送"], ["GUIDE"], "HANDOFF"))
    add("goal_switch", "P01", turn("耳机没收到，先整理给商家的核查说明。", ["只生成人工待确认摘要"], ["GUIDE"], "HANDOFF"),
        turn("现在想申请退款，请整理退款原因给我核对，不是人工说明。", ["按本轮意愿改为退款摘要", "签收争议人工核验，草稿非批准"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"))
    add("goal_switch", "G05", turn("耳机按键卡住了，先准备给商家看的说明。", ["人工草稿未核验"], ["GUIDE"], "HANDOFF"),
        turn("不需要那份说明了，也不用发出去，这个问题结束。", ["取消/结束原事项，无可操作摘要", "不能声称撤销不存在的实际核查单"]))
    add("goal_switch", "P02", turn("台灯没到，先帮我写申请原因。", ["退款产物待确认"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"),
        turn("不写申请了。只告诉我申请之后在哪查看状态？", ["退款准备停止，GUIDE解释进度", "无摘要或假建单"], ["GUIDE"]))
    add("conflict_missing", "P01", turn("耳机物流是签收，但本人没有包裹。你能直接认定已经收到吗？", ["承运记录不等于实际收货", "冲突人工核验，不作确定本人已收判断"], ["SHIPMENT"]))
    add("conflict_missing", "P02", turn("我以为台灯还在路上，麻烦核对现在状态并说说能怎样处理。", ["以当前LOST而非客户旧在途判断", "说明需核验/本店相关政策"], ["SHIPMENT", "POLICY"]))
    add("conflict_missing", "G05", turn("耳机可能坏了，你能确定是质量问题并直接帮我退款吗？", ["客户单方损坏不等于核验", "不能自动批准/退款，可追问症状或人工核验"], ["POLICY"]))
    add("conflict_missing", "P01", turn("我不知道有没有家人收，先问签收争议要提交哪几样必需材料。", ["不虚构必交清单，按签收条件人工核验", "不把不确定代收当已排除"], ["POLICY"]))
    add("tool_failure", "F01", turn("物流查询打不开时，你能断定我的包裹丢了吗？", ["调用失败如实说明，不能当LOST", "可提出合理替代核验或独立人工路径"], ["SHIPMENT"]))
    add("tool_failure", "F02", turn("帮我查台灯运输记录，看不到就告诉我看不到，不要猜。", ["忠实说明冻结上游错误/状态", "不把失败改写为不存在或丢失"], ["SHIPMENT"]))
    add("tool_failure", "P03", turn("耳机这笔实付多少钱？如果订单接口读不到，请说明原因。", ["不得从商品展示代替订单实付", "订单失败如实表达"], ["ORDER"]))
    add("tool_failure", "F01", turn("先核对物流，我还没拿到。", ["失败不能编造当前状态"], ["SHIPMENT"]),
        turn("既然查不出来，只帮我整理给商家的核查说明，先别发送。", ["人工草稿与未核验陈述，故障非丢失", "不重新无限查询失败来源"], ["GUIDE"], "HANDOFF"))
    add("compound", "P02", turn("台灯一直没收到，查物流、说明丢失退款前提，再给我原因草稿，不提交。", ["三个要求均回应，LOST/无有效签收/人工核验", "金额来源/退款草稿用途正确"], ["ORDER", "SHIPMENT", "POLICY"], "REFUND"))
    add("compound", "P01", turn("签收的耳机我没收到：核对物流，再解释争议怎么处理，以及商家能不能看到全部私聊。", ["实际物流/政策/指南三域分清", "人工核验且私有对话不自动全共享"], ["SHIPMENT", "POLICY", "GUIDE"]))
    add("compound", "G05", turn("耳机转轴松了；我不要退款，想先看核查摘要，也想知道补充后是不是另开一单。", ["人工未核验摘要且待确认，无退款", "补充接续原核查，不自动新建"], ["GUIDE"], "HANDOFF"))
    add("compound", "P02", turn("我问两件事：物流现在怎样；如果以后要退款，是否每笔都能部分退一点？先别申请。", ["实时LOST与一般政策条件分开", "仅单行全部数量全额，无操作摘要"], ["SHIPMENT", "POLICY"]))
    for case in cases:
        if case["id"] in {"Q25", "Q28"}:
            case["snapshot_id"] = "P01"
            case["snapshot_override"] = {"tool": "get_shipment_trace", "status": 503,
                                          "body": {"error": "SOURCE_UNAVAILABLE"}}
    return {"version": "customer-quantification-agent-v1", "origin": "CODEX_AUTHORED_SYNTHETIC",
            "independent_holdout": False, "snapshot_source": "evals/customer-agent-live-v3/cases.json",
            "groups": ["dynamic", "fixed"], "repeats": 2, "cases": cases}


def rag_queries():
    # Required source blocks are authored before any ranking; no best-ranked chunk labels.
    entries = [
        ("jd-general", "非PLUS买家因为个人喜好退一件完好的普通商品，返程运费由谁承担，会员有什么不同？", ["b0003"], "个人原因须完好，普通买家自担，PLUS例外。"),
        ("jd-general", "定制商品和鲜活商品都还没用，能只凭七天承诺要求无理由退吗？", ["b0008", "b0009", "b0010"], "两类均列于无理由例外，保留引导范围。"),
        ("jd-general", "第三方送来的订单查不到有效签收日期，应该如何认定实际到货时间？", ["b0007"], "客服结合距离等与客户人工确认。"),
        ("jd-general", "自提订单与第三方配送订单，退换货的收货日期分别看什么？", ["b0006", "b0007"], "自提实际签收；第三方实际到货与缺签收人工确认。"),
        ("jd-general", "客户说商品漏液属于运输损坏，售后是否无需核查，照片是否必交？", ["b0003"], "物流损须核查属实，可能要求照片/快递证明而非必交。"),
        ("jd-general", "发票与商品信息对不上，又被涂改，还能按总则正常办理退换吗？", ["b0014", "b0018"], "凭证不符/涂改列于不予办理范围。"),
        ("jd-general", "退货前评价所得京豆已经用掉，退款会怎么处理？", ["b0020"], "应扣京豆及优惠，已用从退款金额扣。"),
        ("jd-general", "在线下载的软件和已经拆封的音像，是否适用无理由退货？", ["b0008", "b0011"], "数字商品例外含下载/拆封。"),
        ("jd-digital", "手机返修前资料要谁备份，平台会保存和导出数据吗？", ["b0012"], "客户自行导出，平台不提供保存/导出。"),
        ("jd-digital", "数码商品质量问题寄回时，要带哪些资料，电子发票也寄吗？", ["b0010"], "报告及附件包装凭证等一并，电子发票无需返回。"),
        ("jd-digital", "拆开包装刮了防伪码但没激活，能直接按七天无理由处理吗？", ["b0007", "b0008", "b0019"], "完好一般条件受防伪码例外限制。"),
        ("jd-digital", "收货时发现外观异常与隔天才发现，应该分别怎么做？", ["b0015"], "当场指出拒收；签收后24小时申请，可能需照片。"),
        ("jd-digital", "当地没有检测中心，可代检代修吗，周期怎么算？", ["b0016"], "代检7-15天代修30天，签收起不含物流且可延长。"),
        ("jd-digital", "修好的数码商品寄回后外观有问题，发现后能拖几天再反馈吗？", ["b0016"], "及时检查，24小时反馈，超时无法处理。"),
        ("jd-digital", "数码商品性能故障已修两次仍不好，需要什么凭据再申请退换？", ["b0017"], "三包有效期/两次维修/有效维修记录，同型号或依三包。"),
        ("jd-digital", "退数码商品赠品找不到，会影响主商品退款吗？换货也必须退赠品吗？", ["b0021"], "赠品缺失不能全额退款，换货无需返回。"),
        ("mi-self-operated", "有品页面写自营，怎样确认该规则适用的销售主体？", ["b0003"], "公示自营主体销售且小米开具发票。"),
        ("mi-self-operated", "有品收货当天就开始算七天吗？缺失签收日期时怎么判？", ["b0007", "b0038"], "妥投/到货次日起，缺日期结合激活时间距离等。"),
        ("mi-self-operated", "商品外箱明显坏了但当场接收，有品规则如何看待包装状态？", ["b0011"], "应拒收，未拒收视包装无损。"),
        ("mi-self-operated", "商品功能正常但授权激活或留下难恢复的使用痕迹，还符合无理由吗？", ["b0012", "b0023"], "授权/激活/难恢复痕迹为例外。"),
        ("mi-self-operated", "有品无理由退货里怎样理解商品完好，附件和标识能缺少吗？", ["b0012", "b0022"], "原品质功能及本身配件商标标识齐全。"),
        ("mi-self-operated", "退货时赠品用过不能退，一处说不完整不办理，一处说扣钱，应怎样保留这两项依据？", ["b0026", "b0032", "b0082"], "保留不完整限制与赠品扣价条款的张力，不武断覆盖。"),
        ("mi-self-operated", "退货礼品卡的钱能变现金吗，购物时用掉的优惠券会回来吗？", ["b0082"], "礼卡退卡不兑现，成功退货优惠券不退。"),
        ("mi-self-operated", "退货运输途中丢件或损坏，谁承担责任？", ["b0086"], "用户须保证安全完整，途中丢损用户责任。"),
        ("ikea-terms", "俱乐部会员退完好家具与普通顾客期限一样吗，需要哪些购物凭证？", ["b0072"], "60天/会员365天，完好凭证发票及银行卡原始凭证。"),
        ("ikea-terms", "宜家食品与裁剪过的商品都保存完好，可以用一般期限退吗？", ["b0072", "b0073"], "一般退货条件受类别例外限制。"),
        ("ikea-terms", "家具拆包发现损坏，通知时限、保留物品和后续退款条件是什么？", ["b0052"], "7日通知/保留检测；宜家责任且不能维修全额款运费。"),
        ("ikea-terms", "订单付了钱才被告知缺货，顾客和网站能取消吗，款项怎么办？", ["b0041"], "双方可取消，已付款退款。"),
        ("ikea-terms", "客户写错地址或者约好配送无人签收，二次运费和原运费怎么处理？", ["b0057"], "已收配送费不退，重送合理二次费。"),
        ("ikea-terms", "尚未派送的宜家订单想改日期或取消，定制商品及已经发生费用怎么处理？", ["b0059"], "可改取消，定制非随时取消，合理费用及宜家违约例外。"),
        ("ikea-terms", "退货发票已抵扣，是带着发票就够还是另有确认手续？", ["b0072"], "需配合红字信息确认流程。"),
        ("ikea-terms", "网上买的家具退回验收后多久办退款，能换个支付方式收款吗？", ["b0078"], "确认无误7日内，原支付方式。"),
    ]
    draft = json.loads((ROOT / "tmp/policy-documents-v1/drafts-audited.json").read_text(encoding="utf-8"))
    docs = {d["source_id"]: d for d in draft["documents"]}
    result = []
    for source, query, blocks, conclusion in entries:
        doc = docs[source]
        atoms = [{"block_id": source + ":" + block} for block in blocks]
        if source == "jd-general" and "b0003" in blocks:
            atoms = [{**atom, "table_row": 3 if len(result) == 0 else 2} for atom in atoms]
        result.append({"id": f"R{len(result)+1:02}", "query": query, "subject": doc["subject"],
            "scope": [{"source_id": source, "raw_sha256": doc["raw_sha256"]}],
            "answerability": "ANSWERABLE", "expected": conclusion,
            "evidence_sets": [atoms],
            "review_origin": "CODEX_SOURCE_REVIEW_NOT_INDEPENDENT", "partition": "acceptance"})
    for source, query in [
        ("jd-general", "我的退款申请编号为123，现在到账了吗？"),
        ("jd-digital", "这笔手机订单当前物流在哪个城市？"),
        ("mi-self-operated", "商家承诺补发的运单号是多少？"),
        ("ikea-terms", "我昨天下单的桌子本周五几点配送？"),
        ("jd-general", "这个卖家提供十年免费延保吗？"),
        ("mi-self-operated", "这家店这周直播承诺的额外运费补贴是多少？"),
        ("ikea-terms", "宜家2026年11月是否延长退货期到两年？"),
        ("jd-digital", "商家客服刚同意的额外赔偿具体是多少元？"),
    ]:
        doc = docs[source]
        result.append({"id": f"R{len(result)+1:02}", "query": query, "subject": doc["subject"],
            "scope": [{"source_id": source, "raw_sha256": doc["raw_sha256"]}],
            "answerability": "NOT_IN_CORPUS", "expected": "冻结政策不含此实时事实或额外承诺，不可从相关条文推断。",
            "evidence_sets": [], "review_origin": "CODEX_SOURCE_REVIEW_NOT_INDEPENDENT", "partition": "acceptance"})
    return {"version": "customer-quantification-rag-v1", "origin": "CODEX_SOURCE_AWARE_SYNTHETIC",
        "independent_holdout": False, "semantic_overlap_with_prior_sets": True,
        "corpus": "tmp/policy-documents-v1/children-final.json", "queries": result}


if __name__ == "__main__":
    write("agent-cases.json", agent_cases())
    write("rag-queries.json", rag_queries())
    print("Authored 32 Agent conversations and 40 source-labeled RAG questions; no evaluation executed.")
