# 客服首正文与页面体验收尾：工程步

2026-10-24，用户批准收尾两项体验，实施[本批说明](../../docs/customer-agent-latency-close-v1.md)。READ_FACTS新增可选模型policy_query，仅POLICY也是当前缺口时接受；独立条件检索可与两事实选择同一轮，SDK仍逐项计预算、记journal及检查fence。原两事实动作和事后补查保持。

## 工程验证

| 检查 | 实际命令和结果 | 记录 |
| --- | --- | --- |
| 失败先行 | `pytest agent/tests/unit/test_support_evidence_batch.py`，新10例4失败/6通过 | [red.txt](red.txt) |
| 针对 | 新Query批次/原事实批次/政策/目标核对共44通过 | [targeted.txt](targeted.txt) |
| 全客服单元/合同 | `test_support*.py`加两个support合同文件，506通过0跳过 | [unit.txt](unit.txt) |
| 真PG/API/流式/恢复 | evidence_batch、fact_batch、refund_policy、goal_review、orchestrated、summary_grounding、stream七文件17通过0跳过 | [runtime.txt](runtime.txt) |
| 静态 | 3源码strict mypy，3源码2测试Ruff；测试导入分隔首次已修正 | [static.txt](static.txt) |

同证据脚本4→3模型调用，2业务读取/2本地读取、最终内容和引用保持。完整恢复0发送；两事实已完成、政策未开始时中断，恢复只执行剩余政策/最终模型，预算不重置；两事实后fence改变阻断政策。无效Query/不必要政策/本地预算和政策源失败明确处理，事实不同可继续改Query搜索。仅脚本证明协议与恢复，不能冒充真实生成提速。

本工程步0供应商请求，usage2359保持；只写所属PG临时schema，公共11表/旧业务/188历史报告/四历史脏文件核对见[audit.json](audit.json)。PG暂留给已批准的有限真实确认。浏览器工具仍返回Work设置关闭本地浏览器控制，真实页面尚未验收，未启动Java/Web。

下一步冻结相同3输入，最多18请求各题一次，独立记录新有效首正文、请求数及质量。页面权限可用后另进行单轮及原草稿刷新确认，最多12请求，不提交业务申请；无权限则保留未验证项。
