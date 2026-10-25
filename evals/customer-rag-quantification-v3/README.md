# 售后政策扩展问题集

100道作者构造题：40开发/60验收，80可答/20无法由本政策库回答。标签由Codex根据原文审查，非独立人工盲测。

开发题来自京东/小米有品3篇文档，验收题来自其他品牌12篇文档；相同来源不跨两组。所有文档均在索引中，按品牌范围统一过滤。验收题排名尚未运行。

五类各20题，其中每类8开发/12验收；20题无法回答含8政策缺口和12业务或私有事实缺失。所有证据在queries.json以原文跨度/hash绑定，答案要点是人工可读的源审判据，不能用关键词相等自动判语义正确。

| 编号 | 分组 | 类别 | 问题 | 必要依据 |
| --- | --- | --- | --- | --- |
| V3Q001 | development | ordinary | 京东自营数码产品，退货和换货分别有多少天？ | jd-digital:b0005 |
| V3Q002 | development | ordinary | 京东数码商品因质量问题退回，电子发票也要打印寄回吗？ | jd-digital:b0011 |
| V3Q003 | development | ordinary | 有品上标注的自营商品具体由谁销售，发票由谁开？ | mi-self-operated:b0003 |
| V3Q004 | development | ordinary | 小米有品售后退换货地址在哪里获取？ | mi-self-operated:b0040 |
| V3Q005 | development | ordinary | 小米有品寄回售后可以上门取件吗？ | mi-self-operated:b0043 |
| V3Q006 | development | ordinary | 小米有品这份自营售后规则也适用港澳台吗？ | mi-self-operated:b0087 |
| V3Q007 | development | ordinary | 小米有品确认收到退货后多久办理退款，退到哪里？ | mi-self-operated:b0076 |
| V3Q008 | development | ordinary | 京东自营没有质量问题的商品，申请七天无理由退货要谁承担返回运费？ | jd-general:b0009 |
| V3Q009 | acceptance | ordinary | Apple官网购买符合退货条件的商品，应该多久内申请退货？ | apple-returns:b0004 |
| V3Q010 | acceptance | ordinary | Apple官网退货提供免费上门取件吗？ | apple-returns:b0015 |
| V3Q011 | acceptance | ordinary | Apple寄错商品了，我要联系哪个客服渠道？ | apple-returns:b0037 |
| V3Q012 | acceptance | ordinary | 华为手机送修之前，自己保存的数据需要做什么处理？ | huawei-phone:b0035 |
| V3Q013 | acceptance | ordinary | 三星商城退款会退回哪个支付渠道？ | samsung-refund:b0002 |
| V3Q014 | acceptance | ordinary | 三星产品性能故障退换货，需要自己付运费吗？ | samsung-notes:b0002 |
| V3Q015 | acceptance | ordinary | 宜家俱乐部会员和普通顾客，完好商品的退货期限分别是多少？ | ikea-returns:b0002 |
| V3Q016 | acceptance | ordinary | 宜家网上买的完好商品能带到附近商场退吗？ | ikea-returns:b0012 |
| V3Q017 | acceptance | ordinary | 索尼产品因性能故障申请退换，需要哪种检测证明？ | sony-service:b0034 |
| V3Q018 | acceptance | ordinary | 索尼2018年及之后上市的耳机整机保修多久？ | sony-service:b0013 |
| V3Q019 | acceptance | ordinary | 平板电视约好了送货安装调试，三包期从发票日还是安装完成后开始？ | sony-warranty:b0043 |
| V3Q020 | acceptance | ordinary | 华为手机免费维修时，包装和赠品一定都要带吗？ | huawei-phone:b0034 |
| V3Q021 | development | colloquial | 京东买的硬盘要返修，你们能替我把照片先倒出来吗？ | jd-digital:b0013 |
| V3Q022 | development | colloquial | 京东买的手机卡顿，刷个系统就能好，也一定要整机退回吗？ | jd-digital:b0015 |
| V3Q023 | development | colloquial | 京东买的东西我把防伪涂层刮了，但没用，能走无理由吗？ | jd-digital:b0020 |
| V3Q024 | development | colloquial | 京东买的主商品我想退，赠的那件找不到了，还能全额退吗？ | jd-digital:b0022 |
| V3Q025 | development | colloquial | 有品客服还没回我，我先把东西寄过去可以吧？ | mi-self-operated:b0080 |
| V3Q026 | development | colloquial | 有品商品的发票型号和机子对不上，能直接给我换吗？ | mi-self-operated:b0034 |
| V3Q027 | development | colloquial | 有品设备的外壳用久了磨裂了，不是触摸屏，能当免费维修吗？ | mi-self-operated:b0059, mi-self-operated:b0052 |
| V3Q028 | development | colloquial | 有品退货我在寄回路上弄丢了，你们能照样给我退款吧？ | mi-self-operated:b0086 |
| V3Q029 | acceptance | colloquial | Apple订单还写着正在处理，我地址填错了，还能改吗？ | apple-orders:b0029, apple-orders:b0030 |
| V3Q030 | acceptance | colloquial | Apple还没准备发货，我突然不想要了，能直接取消整单吗？ | apple-orders:b0047, apple-orders:b0048 |
| V3Q031 | acceptance | colloquial | Apple一单买了几件只退一件，剩下东西的发票怎么办？ | apple-returns:b0009 |
| V3Q032 | acceptance | colloquial | 华为Windows笔记本刚联网进了桌面，我不喜欢，七天内还能无理由退吗？ | huawei-laptop:b0023 |
| V3Q033 | acceptance | colloquial | 华为笔记本发票保修卡都丢了，也拿不出别的购机证据，保修起点怎么算？ | huawei-laptop:b0019 |
| V3Q034 | acceptance | colloquial | 华为授权第三方平台买的笔记本，我直接找华为办退货行吗？ | huawei-laptop:b0004 |
| V3Q035 | acceptance | colloquial | 三星手机已经激活了，但一点划痕都没有，能无理由退吗？ | samsung-conditions:b0002 |
| V3Q036 | acceptance | colloquial | 三星洗衣机我已经装好洗过一次了，没坏，只是不喜欢，可以七天无理由吗？ | samsung-conditions:b0002 |
| V3Q037 | acceptance | colloquial | 三星买手机送的赠品我留着，手机退了还能一分钱不少地退吗？ | samsung-notes:b0002 |
| V3Q038 | acceptance | colloquial | 宜家家具拆箱才看到破了，我是不是现在就能把破件扔掉？ | ikea-terms:b0052 |
| V3Q039 | acceptance | colloquial | 宜家椅子我坐了一段时间有磨痕，不是质量问题，会员是不是也能随便退？ | ikea-returns:b0006 |
| V3Q040 | acceptance | colloquial | 索尼耳机掉水里坏了，反正还在保修期，是不是免费修？ | sony-service:b0031 |
| V3Q041 | development | exact | 京东数码到货后才发现外观异常，签收后申请物流损退换的时限是多久？ | jd-digital:b0016 |
| V3Q042 | development | exact | 当地没有厂家维修中心，京东代检和代修分别预计多久？ | jd-digital:b0017 |
| V3Q043 | development | exact | 京东数码性能故障在三包期内修了两次仍不能用，换货需要什么凭证？ | jd-digital:b0018 |
| V3Q044 | development | exact | 京东数码外包装至少建议保留多少天？ | jd-digital:b0019 |
| V3Q045 | development | exact | 有品物流没有有效签收时间，七天退货窗口怎么判定？ | mi-self-operated:b0038 |
| V3Q046 | development | exact | 小米有品保外维修费通知后七天未付，商品怎么处理？ | mi-self-operated:b0073 |
| V3Q047 | development | exact | 小米有品退货成功，原先用的优惠券和礼品卡余额分别怎么退？ | mi-self-operated:b0082 |
| V3Q048 | development | exact | 小米保内服务采用以换代修，换新的商品是否重新有退换期和保修起点？ | mi-self-operated:b0048 |
| V3Q049 | acceptance | exact | Apple官网微信钱包支付的退货退款，页面规定几个工作日完成操作，查哪里？ | apple-returns:b0023 |
| V3Q050 | acceptance | exact | Apple官网电汇支付退款，需要提供什么账户，几个工作日办理？ | apple-returns:b0026 |
| V3Q051 | acceptance | exact | Apple预定三小时快送，要求什么下单付款时间，有没有地区限制？ | apple-shipping:b0006, apple-shipping:b0007 |
| V3Q052 | acceptance | exact | 华为笔记本电池和主板的保修期限一样吗？ | huawei-laptop:b0009 |
| V3Q053 | acceptance | exact | HUAWEI MateBook X Pro 2023 13代酷睿版是否在两年上门服务型号表里？ | huawei-laptop:b0011 |
| V3Q054 | acceptance | exact | 华为线上买的手机签收次日起第10天出现非人为性能故障，能选哪些免费处理？ | huawei-phone:b0019 |
| V3Q055 | acceptance | exact | 三星商城显示器没有性能故障而退货，配送费按什么标准收？ | samsung-notes:b0002 |
| V3Q056 | acceptance | exact | 三星商城智能手机正常出库后无理由退货，双向配送费用标准是多少？ | samsung-notes:b0002 |
| V3Q057 | acceptance | exact | 宜家线上购物发票中心周末能处理发票吗，工作日几点开？ | ikea-returns:b0013 |
| V3Q058 | acceptance | exact | 宜家退货验收无误后，规定几日内办理退款？ | ikea-returns:b0011 |
| V3Q059 | acceptance | exact | 索尼投影机整机和灯泡分别保修多久？ | sony-service:b0017 |
| V3Q060 | acceptance | exact | 索尼平板电视整机和显示屏等主要部件保修各几年？ | sony-service:b0007 |
| V3Q061 | development | compound | 京东自营商品说是质量问题，谁来确认、要什么证明，退回运费谁出？ | jd-general:b0004 |
| V3Q062 | development | compound | 京东非京东物流送来的商品，物流缺签收时间，退换窗口和收货日如何确认？ | jd-general:b0003, jd-general:b0008 |
| V3Q063 | development | compound | 京东自营下载的软件和普通完好商品都能七天无理由吗，普通退货运费谁付？ | jd-general:b0009, jd-general:b0012 |
| V3Q064 | development | compound | 京东代修的存储设备寄出前数据怎么处理，修好收到发现外观问题多久反馈？ | jd-digital:b0013, jd-digital:b0017 |
| V3Q065 | development | compound | 有品自营质量问题申请退换，检测和双向运费分别怎么处理？ | mi-self-operated:b0008, mi-self-operated:b0046 |
| V3Q066 | development | compound | 有品订单只退部分商品，电子发票和没有退回的赠品怎么处理？ | mi-self-operated:b0085, mi-self-operated:b0082 |
| V3Q067 | development | compound | 小米有品寄修前数据和快递面单需要分别准备什么？ | mi-self-operated:b0068, mi-self-operated:b0069 |
| V3Q068 | development | compound | 有品退货的外包装指快递纸箱还是厂家包装，返程损坏是谁负责？ | mi-self-operated:b0083, mi-self-operated:b0086 |
| V3Q069 | acceptance | compound | Apple订单已经无法在线取消，我还想退，接下来走哪个入口、申请期限是多少？ | apple-orders:b0050, apple-returns:b0004 |
| V3Q070 | acceptance | compound | Apple官网微信付款并付过快送费，退货后快送费退不退，退款操作多久完成？ | apple-returns:b0020, apple-returns:b0023 |
| V3Q071 | acceptance | compound | Apple企业抬头发票已经抵扣，现在部分退货，公司财务和剩余发票分别怎么办？ | apple-returns:b0009, apple-returns:b0010 |
| V3Q072 | acceptance | compound | Apple包裹运输中疑似丢了，你们怎么调查？能保证精确到几点送达吗？ | apple-shipping:b0068, apple-shipping:b0057 |
| V3Q073 | acceptance | compound | 华为手机整机换新和只换一个部件，主机及部件保修期分别怎么续？ | huawei-phone:b0030 |
| V3Q074 | acceptance | compound | 华为MateBook X Pro 2023 13代酷睿版在两年内非人为故障，是不是所有地方都免费上门？ | huawei-laptop:b0011, huawei-laptop:b0012, huawei-laptop:b0013 |
| V3Q075 | acceptance | compound | 华为Windows笔记本联网激活后想无理由退，如果确有非人为性能故障，和无理由退是一回事吗？ | huawei-laptop:b0023, huawei-laptop:b0022 |
| V3Q076 | acceptance | compound | 三星显示器包装完好也没揭原厂膜，不是质量问题，七天内退货条件和配送费怎么算？ | samsung-conditions:b0002, samsung-notes:b0002 |
| V3Q077 | acceptance | compound | 三星商城买的优惠套装想拆开只退一件，另外信用卡手续费能一起退吗？ | samsung-notes:b0002, samsung-refund:b0002 |
| V3Q078 | acceptance | compound | 宜家送来的家具拆包发现破损，几天内通知、要不要留破件，什么情况下才全额退货款和运费？ | ikea-terms:b0052 |
| V3Q079 | acceptance | compound | 宜家用两种方式付款，送货当天取消，退款怎么分配，原运费也退吗？ | ikea-returns:b0018, ikea-returns:b0020 |
| V3Q080 | acceptance | compound | 我在香港指定渠道买的索尼正品手机，保修期内到内地能连配件一起联保，还能直接换新退机吗？ | sony-service:b0039 |
| V3Q081 | development | unanswerable | 京东海外购跨境商品退货后关税如何逐项退还？ | 缺失：现有自营总则和数码细则未给跨境税款退还规则 |
| V3Q082 | development | unanswerable | 京东这款数码产品三十天价保的差价计算公式是什么？ | 缺失：自营售后文档没有价格保护计算规则 |
| V3Q083 | development | unanswerable | 京东送修的硬盘里那张毕业合照现在还在吗？ | 缺失：文档不能访问用户设备数据 |
| V3Q084 | development | unanswerable | 京东退货寄回地址帮我确定到具体门牌，订单信息我还没给。 | 缺失：文档没有本次售后地址与订单绑定 |
| V3Q085 | development | unanswerable | 有品安心保碎屏险的免赔额和一年赔付次数是多少？ | 缺失：自营售后规则没有该保险合同和赔付条款 |
| V3Q086 | development | unanswerable | 有品配送延误一天赔偿多少钱，按哪个公式计算？ | 缺失：自营售后文档未列配送延误赔偿公式 |
| V3Q087 | development | unanswerable | 有品这次售后寄回的包裹现在在哪个网点？ | 缺失：规则无物流实时轨迹 |
| V3Q088 | development | unanswerable | 有品维修中心今天把我的主板换成哪个序列号了？ | 缺失：规则没有维修结果及部件序列号 |
| V3Q089 | acceptance | unanswerable | 在日本Apple零售店购买的商品，当地适用的完整退货期限是什么？ | 缺失：冻结资料为中国大陆购买帮助，不含日本门店适用政策 |
| V3Q090 | acceptance | unanswerable | Apple帮我查这笔订单真实的取消状态，我没有提供订单号。 | 缺失：文档不是具体订单状态接口 |
| V3Q091 | acceptance | unanswerable | Apple我家所在小区今天几点能收到这单货？ | 缺失：帮助文档不含本单配送轨迹且不承诺精确时间 |
| V3Q092 | acceptance | unanswerable | 华为碎屏服务宝这一款的免赔额和保障次数是多少？ | 缺失：手机基础售后政策未包含该增值保障合同 |
| V3Q093 | acceptance | unanswerable | 华为我这个SN今天实际还剩多少天保修？ | 缺失：无该SN保修权益或购买时间数据 |
| V3Q094 | acceptance | unanswerable | 华为你们能保证把我电脑丢失的文件全部恢复吗？ | 缺失：政策无数据恢复能力或结果保证 |
| V3Q095 | acceptance | unanswerable | 三星商城延迟发货，每天赔偿多少，封顶多少？ | 缺失：退换货和退款FAQ没有延迟发货赔偿标准 |
| V3Q096 | acceptance | unanswerable | 三星这笔信用卡订单退货后确定到账金额是多少？我没提供金额和手续费。 | 缺失：无本单金额、手续费和已保留商品等输入 |
| V3Q097 | acceptance | unanswerable | 三星能给我查今天仓库还有多少台同型号换货库存吗？ | 缺失：政策仅说明缺货处理，不包含实时库存 |
| V3Q098 | acceptance | unanswerable | 宜家床垫质保逐年折旧比例的完整表是什么？ | 缺失：退货和电商条款未给床垫质保逐年折旧表 |
| V3Q099 | acceptance | unanswerable | 宜家今天送货给我的司机姓名和车牌是什么？ | 缺失：协议无实时配送人员资料 |
| V3Q100 | acceptance | unanswerable | 索尼我的耳机维修今天已经换了哪一个零件？ | 缺失：服务政策无具体维修工单结果 |
