# 当前客服架构有限收口验收

2026-10-25。按用户授权冻结当前架构，新增开发可见合成3组11轮，只执行一次，每批最多40真实供应商请求，不用追加题或更换措辞补分。

- [规格](../../docs/customer-final-acceptance-v1.md)、[固定输入与逐轮判据](../../evals/customer-final-acceptance-v1/scenarios.json)、[冻结manifest](../../evals/customer-final-acceptance-v1/manifest.json)。
- 准备验证：`python -m pytest agent/tests/unit/test_customer_final_driver.py agent/tests/unit/test_customer_current_eval.py -q`，7通过；新驱动及测试Ruff通过。
- `python -m scripts.accept_customer_final_v1 freeze`及`check`通过；[预检](preflight.json)确认原PG/政策/索引可用，尚无新模型请求，ledger起点2381。
- 真实模型、实际接受状态、PG临时schema、真实只读政策RAG；订单/物流HTTP事实为受主体约束的冻结响应。本批不重新验收Java/UI，不提交申请或共享核查。

准备6ad2853普通push核实后，仅一次执行`python -m scripts.accept_customer_final_v1 execute`。全部11轮保留，不更新简历原文。

## 实际结果：保留架构，暂不宣告质量完全冻结

[全部会话](conversations.md)、[逐轮源审](source-review.json)、[原始运行与请求/来源](runtime-results.json)、[离线根因复现](offline-diagnosis.json)。真实DeepSeek 29请求，108934输入/4517输出token，未知/估算请求均0，ledger2381→2410，未追加题或真实重跑。run.spend输入122824是本地预算计数；供应商usage才是本报告token消耗依据，两者不混用。

| 口径 | 结果 |
| --- | --- |
| 技术发布 | 10/11成功；F03第3轮INVALID_DECISION |
| 全部预设逐轮判据 | 8/11通过，1/11部分完成，2/11阻断 |
| 纠正、独立人工与隐私会话F02 | 3/3通过 |
| 新收费重跑/修改提示或生产实现 | 0 |

F01第4轮正确生成329元退款草稿并保留签收争议及待核验前提，但新建APPLICATION事项后，原暂停LOGISTICS事项未RESUME，所以严格记录部分完成，不在看到结果后放宽判据。两个阻断如下：

1. **纠正范围不完整（F01/5）**：模型知道已找到包裹，事项RESOLVED、操作取消，回答也正确结束；但REPLACE只指向最初一条未收到陈述，后续“目前我还没有拿到”“我还是没拿到”仍ACTIVE。离线恢复确认它们仍会进入下一版本有效记忆。这里只证明状态风险，没跑下一轮，不能声称已发生错误申请。
2. **摘要原话选择失败（F03/3）**：理解正确选择MERCHANT_REVIEW，首次摘要却选了历史材料追问；修正后又选了含旧退款意愿的整段历史。当前ground_summary仅允许本轮片段或ACTIVE记忆中的完整quote，二者均不合法，原有限修复后终止。离线逐元素复现同样拒绝；用合法ACTIVE原话和本轮请求则通过，证明存在合法产物，不能把离线替换当作真实模型修复成功。两份被拒候选还重述未在本run读取的旧政策，未作为有效发布答案计分。

原因不是本批RAG召回不到：3次实际政策读取均为绑定本店版本的6条COMPLETE_SMALL_SET，相关签收/丢失/人工核验条款已获得并使用。失败轮根本未发政策检索。本批也不能证明大语料检索质量或新RAG提升。

## 速度、次要问题及验证边界

成功10轮运行完成中位3.63秒，范围2.66–6.54秒；9轮有保留正文的首delta中位2.89秒，范围2.17–5.09秒。F01/1候选正文reset后最终正常发布，不能把被清除首delta算有效首正文；F03/3两次候选被拒，未进成功分布。均为服务端runtime事件接收时间，不是浏览器耗时；没有新页面验收、稳定4秒SLA或总体P95结论。正文仍偏长、部分重复，F03/2多引了未使用的在途条款，单列为次要问题。

离线复核命令`python -m scripts.review_customer_final_v1`通过原拒绝复现/合法候选/下一版本记忆断言；初次Ruff发现两个新脚本import问题，已修正并重查。本批无业务代码调整，不为追满分换框架或继续加真实模型轮。

## 有限后续范围

当前主架构继续保留，暂缓将本批写成简历成功率。若继续实施，仅处理两个职责边界：让模型选择由程序提供的合法摘要原话引用，由程序装配原文并给出具体非法元素反馈；让一次语义纠正显式覆盖同一事项中多条失效陈述，并原子校验更新。不能按整RECEIPT主题全删，也不能允许所有历史原文绕过有效性检查。同步明确“事项继续、目标变化”的状态合同，避免旧事项永远暂停；先离线通用变体/原输出回放，再另定有限真实确认，不默认重开完整优化周期。

最终保留审计及资源恢复见[final-audit.json](final-audit.json)。原public/政策/索引及188历史报告保持，临时schema导出清理；项目所属资源恢复关闭，Docker及原数据卷保留。
