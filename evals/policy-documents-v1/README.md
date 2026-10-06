# 原始政策文档探针 v1

2026-10-06，4份官方HTML页面、3个来源主体；不是本项目商家上传、不是已采用政策、不是独立Gold。

[sources.json](sources.json)保存URL、原始字节hash、严格解码编码、明确正文定位和结构风险；[manifest.json](manifest.json)冻结该清单。原文缓存位于仓库忽略的`tmp/policy-documents-v1/*.html`，不推送外部版权全文。离线复现必须保留这些原文件；仅有URL无法保证重新取回同一版本。抓取元数据同目录`*.capture.json`，日期以本轮报告为准，原始页面未公布的政策生效日期保持null。

缓存文件不得改名冒充另一来源。后续工具必须核对原文hash；网页变化应另建快照，不能编辑这里的expected_sha256以让旧结果通过。JD两页属于同一来源家族，未来划分开发/测试不能当两个独立商家。

实施协议见[原始文档入库](../../docs/policy-document-ingestion.md)，实际验证见[报告](../../reports/policy-document-ingestion/README.md)。当前仍无独立相关性标签，准确率不计算。旧calibrated-v3和生产索引不变。
