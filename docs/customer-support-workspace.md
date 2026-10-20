# 售后咨询与商家核查使用说明

2026-10-20。[协议](customer-support-contract-v1.md)中的持久会话、人工核查及[Agent只读咨询](customer-agent-implementation-v1.md)已接入网页。客服入口退款摘要确认仍待后续，本页描述当前可操作行为，不把[预期图](ui-customer-agent-v1/README.md)全部视作已完成。本轮使用明确脚本模型验证接线，真实模型回答质量尚未评测。

## 买家

沿[本机运行说明](local-runtime.md)启动后，以平台买家登录，在商城导航点击“售后咨询”。页面先列本人已付款的订单商品，也能从左侧恢复已存在的咨询；每个订单行独立保存消息。还没有订单时先正常模拟购买。

选择商品后点击“发送给助手”，可描述、补充或纠正问题。助手自主选择查订单、物流、历史或本店绑定版本政策，回答可展开查看来源/版本和相关原文。生成期间可继续补充，旧输入的回复不会发布成最新回答；失败时可重新提问或请商家核查。

点击“请商家核查”后可采用并编辑最新助手的转交摘要；调查依据默认不勾选，客户可选择共享本回答的订单、物流和政策依据，并分别选择共享哪些客户原文，确认后才创建核查单。不需要填写退款金额，不会提交退款申请。对话历史引用不会随调查依据自动共享。

转交后默认输入“补充给商家”，消息回到同一核查单；也可显式切换“询问智能助手”，这类咨询及助手回答不自动交给商家。商家回复后可继续补充，或确认问题已解决；解决后再补充给商家会接续原单。咨询不限制为两轮补证。

当前记录自动检查进度，也能手动刷新；读取更早消息时暂停自动刷新，避免阅读中丢失展开的历史。网络结果未确认时只提供“用原请求确认结果”，同一浏览器标签页刷新后仍保留原请求与标识。版本冲突时保留输入并提示刷新，不自动提交过时摘要。

现有“我的售后”退款申请入口继续可用；本批尚未接通咨询内的退款摘要确认与Case关联。

## 商家

以本店商家账号登录，从工作台“咨询核查”进入。仅显示客户已经确认提交给本店的记录：摘要、选定共享原文及此后核查消息。客户未共享的私人记录不出现在商家接口和页面中。

商家选择“核查回复”或“请求客户补充”并发送，客户在原会话看见明确的商家作者。已回复不会自动标成已解决；客户解决后商家发送按钮停用，等待客户后续补充接续。商家不会因为查看页面触发模型，也不能通过此入口退款。

客户确认共享助手调查依据时，商家还能查看对应订单、物流和政策来源/版本；客户编辑后的核查摘要是本次诉求。商家不会看到私有助手聊天，也不会因打开报告触发新调查；最终核查和回复由商家操作。

## Agent链路验收与实图

保留演示库追加Case V28及PG 013；A-TRANSIT使用真实物流接口、已存在READY政策generation与本地BGE向量检索，模型明确mock。独立咨询run保存调用账，重复完成请求复用结果。A-DELAYED保留真实回答与未确认的转交预览，未新增第二份核查单。原交易8表、原咨询4表和旧Agent run已核对保留，见[本批报告](../reports/customer-agent-v1/README.md)。

- [买家查看回答与引用](../reports/customer-agent-v1/images/buyer-answer.png)
- [客户编辑摘要及选择共享依据](../reports/customer-agent-v1/images/buyer-handoff-preview.png)
- [商家查看已确认报告](../reports/customer-agent-v1/images/merchant-report.png)

正式启动仍用`start.ps1`及既有真实模型配置，咨询沿用该模型配置，会产生模型用量；mock只用于明确配置的本地验收，页面标记“脚本模型演示”。本批没有调用付费模型。Java咨询派发默认沿用dispatch开关，也可单独设置`resolveflow.support-agent.enabled`；政策开关沿用`RESOLVEFLOW_POLICY_INDEX=1`。

本批验收临时服务关闭旧Case调查、回调、MQ及退款后台，只开启新咨询派发，网页直连Case；Gateway本批未重验。`scripts/customer_agent_acceptance.py`仅适用于本机保留样本/基线和显式mock咨询环境，使用忽略目录保存原请求；不能指向真实模型环境重放。`scripts/check_customer_agent_runtime.cjs`检查三幅双端实图；没有助手回答时会在A-DELAYED提交一条合成咨询，已有回答则只读复用，转交停在预览。

## 上一批人工链路验证与演示数据

保留演示库追加Case V27，使用此前A-SIGNED/B-SIGNED两笔独立合成订单，产生两段咨询、一个核查单。运行脚本先保存幂等请求，重放不重复追加。A样例演示共享一条原文、商家补问、三次客户补充、商家回复与客户确认解决；B样例保持独立私人咨询。

- [用户选择商品实图](../reports/customer-support-v1/images/buyer-select.png)
- [用户会话实图](../reports/customer-support-v1/images/buyer-conversation.png)
- [用户转交预览实图](../reports/customer-support-v1/images/buyer-handoff.png)
- [商家核查实图](../reports/customer-support-v1/images/merchant-ticket.png)
- [验证报告与局限](../reports/customer-support-v1/README.md)

真实HTTP验收使用临时Case+Commerce与网页直接代理，不启动Python Agent/worker/MQ派发或退款后台；Gateway本批未重验。临时进程收尾关闭，数据/迁移/原交易保留。已有标准启动入口不修改，后续启动会使用新的业务代码和页面。

需要重放验收时，先确保指向上述本地保留演示环境、7笔设计订单已存在，再运行以下脚本；它会写合成咨询消息，但不调用模型或退款接口：

```powershell
.\agent\.venv\Scripts\python.exe scripts/customer_support_acceptance.py
# 网页已启动且Node能解析现有Playwright时，读取双端实图；不提交新消息。
node scripts/check_support_runtime.cjs
```

验收请求保存在忽略目录`tmp/customer-support-v1/acceptance-state.json`，不要删除后在同一会话重复初始化。默认使用既有演示密码；如已修改可通过`RESOLVEFLOW_DEMO_PASSWORD`提供，脚本不输出令牌/密码。
