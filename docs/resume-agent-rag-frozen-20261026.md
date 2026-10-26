# Agent 与 RAG 简历正文

2026-10-26，按用户确认的文案，仅替换桌面量化实验版简历中的 Agent、RAG 两条。其余五条技术点、项目介绍、技术栈及非项目内容保持。2026-10-25 的 Agent 冻结稿作为历史记录保留，本次是用户明确授权的表述更新，指标不变。

## 本次采用正文

- **Agent 自主决策**：基于 AgentScope 构建多轮售后 Agent，根据用户诉求动态查询订单、物流与政策，支持信息纠正及“咨询—摘要确认—售后建单”闭环；较固定分支 Workflow，将**咨询任务成功率由46.9%提升至87.5%**，结合流式输出与调查进度反馈，服务端**平均首正文响应时间为3.37秒**。
- **Agentic RAG 政策检索**：将政策检索封装为 Agent 工具，根据用户诉求按需检索售后依据，构建并评测 BGE 向量与 BM25 混合召回、RRF 融合及 CrossEncoder 精排方案；在自建售后政策评测集中，较纯向量检索，将 **Top-3关键证据完整命中率由75.0%提升至84.4%**，本地热态平均检索耗时约 **135ms**。

## 指标依据与面试展开

- Agent：[原冻结口径](resume-agent-frozen-20261025.md)、[两组正式报告](../reports/customer-workflow-comparison-v2/README.md)、[首正文计量](../reports/resume-agent-freeze-v1/measurement.json)。32个自建模拟场景，两组各一次，Workflow15/32、Agent28/32；3.37秒为49轮实际保留正文的服务端首正文平均时间，3.05秒仍是P50。任务成功率不代表退款执行率，客户确认后由Java建单的功能验收与此对照分别记录。
- RAG：[v3完整开发报告](../reports/customer-rag-quantification-v3/development-report.md)、[原始结果](../reports/customer-rag-quantification-v3/development.json)。40道开发题中32题可答，按首轮Top-3覆盖全部必要原文跨度计，dense24/32，RRF+CE27/32；不是最终回答准确率。每路40题三次共120次计时，RRF+CE平均134.575ms，包含热态Query编码至证据包，不含加载、HTTP、PG或回答生成；检索排名使用缓存文档向量与本地相似度。60题独立验收未运行。
- Agent按需调用政策工具已实现；混合召回/RRF/精排当前是已实现的评测方案，尚未切为生产默认。因此正文保留“构建并评测”，不声称现有Agent默认使用精排。没有为本次文案重跑实验或更改标签、旧评分、生产代码。
- 后续条款定位/父块去重未提高整体完整覆盖，见[保留的消融结果](../reports/customer-rag-clause-v1/results.md)。原75.0%→84.4%仍来自同一v3对照，不混用该后续实验的耗时。讨论中识别到部分Gold可能遗漏等价证据，尚未完成重新标注和复评，本次保持原严格跨度口径及原分数。

## 文件与验证

桌面 `Agent开发实习简历(量化实验版).pdf` 与现有 `andy_style_resume_overleaf/resume-zh_CN_hejunnan_quantification.tex` 已同步更新。个人简历PDF、含个人信息的源文件及备份仅保留本地，不加入Git。

- 输出副本：`output/pdf/Agent开发实习简历(量化实验版_Agent与RAG更新).pdf`。
- 修改前PDF及TeX备份、编译日志、逐项审计和预览：`tmp/pdfs/agent-rag-20261026/`。
- 实际执行：`tmp/pdfs/update_agent_rag_20261026.py` 使用既有XeLaTeX模板，只替换原TeX第118、119行；XeLaTeX以 `-interaction=nonstopmode -halt-on-error -no-shell-escape` 编译成功，0 Overfull，仍为1页。
- pypdf核对去掉这两条后的全文与原PDF一致，所有目标指标存在，旧17.2%/85.8%/2219ms已移除；Poppler渲染后完整页面目视确认通过，字号/风格保持，无遮挡/裁切。发布前核对原文件未被并行修改，输出及桌面PDF哈希一致。
- 本批未运行模型、收费测量、业务测试、Java/前端或数据库操作；不因编辑简历重新跑业务评测。
