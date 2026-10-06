# 原始政策文档探针 v1

2026-10-06，4份官方HTML页面、3个来源主体；不是本项目商家上传、不是已采用政策、不是独立Gold。

[sources.json](sources.json)保存URL、原始字节hash、严格解码编码、明确正文定位和结构风险；[manifest.json](manifest.json)冻结该清单。原文缓存位于仓库忽略的`tmp/policy-documents-v1/*.html`，不推送外部版权全文。离线复现必须保留这些原文件；仅有URL无法保证重新取回同一版本。抓取元数据同目录`*.capture.json`，日期以本轮报告为准，原始页面未公布的政策生效日期保持null。

缓存文件不得改名冒充另一来源。后续工具必须核对原文hash；网页变化应另建快照，不能编辑这里的expected_sha256以让旧结果通过。JD两页属于同一来源家族，未来划分开发/测试不能当两个独立商家。

实施协议见[原始文档入库](../../docs/policy-document-ingestion.md)，实际验证见[报告](../../reports/policy-document-ingestion/README.md)。当前仍无独立相关性标签，准确率不计算。旧calibrated-v3和生产索引不变。

本机离线解析（不需要Docker/模型密钥），在项目根目录运行：

```powershell
agent/.venv/Scripts/python.exe scripts/policy_documents.py --output tmp/policy-documents-v1/parsed-next.json
```

输出文件须不存在，脚本默认不联网、不覆盖历史输出。结果包含结构块、章节路径、表格单元格、原文行列/字符区间、原片段hash、格式疑点及PENDING_REVIEW。定位针对严格解码的原文件，原片段hash使用该字符区间重新编码UTF-8，不等于原始HTTP字节hash。

明确需要重取同一冻结快照时可以追加`--fetch --cache tmp/policy-documents-refetch`；缓存目录必须不存在，网页hash变动即拒绝，不能把新字节当旧版本。此参数不是自动接受新网页版本的入口。网页可达和获取同一快照是两种不同结果。

当前解析器保留复杂合并表格及标记，未展开合并单元格的完整逻辑网格；内嵌加粗标题仅标候选，不自动认定为章节。JD正文容器还含面包屑/下载入口，内容质量尚待确认。图片/OCR、动态JS正文、章节跨文档关联、语义去重/冲突检测、条款发布和新的检索索引未实现，不能据提取246块就称原始文档入库全部完成。
