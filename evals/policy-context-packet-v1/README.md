# 固定依据集合与聊天模型 token 实验

本批接续[标题/并集实验](../policy-representation-v1/README.md)，只改变已选依据的表达。上一批去重后继续贪心准入，可能因为空间释放而新增章节。本批先复现旧整context选择，封存context IDs、来源块集合与指纹，再去重；腾出的空间不用于新章节。选择器不读取query文本、标签、答案或案例编号。

[manifest](manifest.json)在测量前冻结正文BODY、原58条dense/BM25排名、前2/5、8000内容字符、旧query/依据/构建器，以及本批实现、测试和官方DeepSeek V4.1 tokenizer的文件hash。没有重新embedding或调用聊天模型。来源仍4个官方HTML/3家族，29问/41依据原子均为既有待审版本。

## 两种表达

两种包使用相同来源字典、块元数据与context→block引用。来源含网址、主体、原始快照SHA；块含原块ID、文本SHA、原始片段SHA及定位；context含ID、章节路径、有序block refs及全文SHA。

- `repeated`：完整context各带全文，重叠块正文可能重复。
- `deduplicated`：每个source/rawsha/block身份的全文只出现一次，context通过有序引用重建。相同文字但不同来源或快照不合并。

这是一套刻意包含完整定位信息的**实验溯源包**，不是生产SEARCH_POLICY协议，也不是推荐全部注入模型的包。`s0/b0`等短引用只在本包内解析；EXTERNAL来源不会获得生产政策权限。完整版原文和证据链保存在忽略的tmp缓存，提交报告不含政策全文。

选择和表达各自校验：来源/主体/快照、原文/hash、引用唯一性和完整context保持一致；选择后的源块/定位/网址漂移触发拒绝。相同文本却有不同块身份的context别名明确报ambiguous，不通过文本hash静默丢弃出处。输出审计另外从传输块重建每个context，确认无新增或丢失的块。

## token 与长度探针

用项目已有`load_tokenizer()`离线加载V4.1固定hash资产，禁padding/truncation。计数对象是本项目canonical JSON序列化后的**证据包**，不包含system prompt、工具协议、历史消息或供应商chat template，不等于整个Agent请求或实际计费token。

同时测正文拼接的token、完整JSON token和两者差值。`wrapper_delta_tokens`是两种完整字符串计数的差，因token边界变化，不是可以逐字段相加的独立metadata账单。不能将字符节省或正文token节省直接当完整请求节省。

2048/4096/8192仅为离线完整证据包的长度探针，不是API消费/财务限额，也不改变生产预算。超限拒绝整包、packet=null，不截段落或删除例外来凑预算，不继续选别的context。这个实验无法证明模型理解短引用或建议质量提高。

## 运行

需要前批冻结的本机`tmp/policy-documents-v1/children-final.json`和`drafts-audited.json`及其原始缓存链；它们未提交全文。原始网页可能更新，重新下载不保证相同hash。tokenizer来自既有仓库资产和依赖锁，不另下载模型。

```powershell
agent/.venv/Scripts/python.exe scripts/policy_context_packet_eval.py --output reports/policy-document-ingestion/context-packet-experiment.json --cache-output tmp/policy-documents-v1/context-packets-v1.json
```

已存在的report或cache路径明确拒绝覆盖；复跑选择新路径。生产依赖源码变动也会让旧manifest拒绝，不能静默更新manifest复写报告。修改参数、实现或引用结构应另冻版本。

[实际报告](../../reports/policy-document-ingestion/context-packet-experiment.json)、[116前缀审计](../../reports/policy-document-ingestion/context-packet-audit.json)、[测试](../../reports/policy-document-ingestion/context-packet-tests.xml)及[命令/结论](../../reports/policy-document-ingestion/README.md)。独立复核0、正式质量null，不以作者草稿选择生产算法。下一步应把系统留存的完整证据链和模型读取的最小引用分开，再做相同集合的token/回查对照；当前完整溯源包不部署。
