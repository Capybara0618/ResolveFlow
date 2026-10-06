# 原始政策文档入库：实施记录

## 2026-10-06 第一批：规格和官方来源

实施[规格](../../docs/policy-document-ingestion.md)、[来源清单](../../evals/policy-documents-v1/sources.json)及冻结manifest。沿用主分支、依赖锁、生产政策/旧评测和四个原有脏文件，不启动数据库写入/付费模型/后台页面。

实际核验官方京东服务总则/数码说明、小米有品自营规则、宜家使用条款；web打开四页均可读，另外Python urllib直接抓取四页HTTP200，原始字节82547/79625/19405/143668，共325245字节。存于忽略目录`tmp/policy-documents-v1`，非敏感HTTP标题/URL/hash元数据同目录保存。JD字节按GB18030解码，MI/IKEA为UTF-8；HTMLParser只读观察确认正文容器分别为div.content/div#wrap/div.bcms-rich-text__content。

只读源码核验确认原导入先YAML进入Java再经内部API供Python建索引；本批不是从真实商家获得的政策。公开材料含范围外换货/维修/运费/发票等说明，全部为外部参考，不映射生产商家，不给予Agent新增动作。

实际命令：PowerShell通过`agent/.venv/Scripts/python.exe -`运行urllib Request/urlopen（25秒超时、4MB读取限制），写原字节和SHA-256；第二条命令用HTMLParser查看meta及正文容器。来源JSON/manifest/hash/缓存大小/严格解码/文档链接用标准库检查，`git diff --check`检查格式。来源无法访问/抓取失败0；未测正式解析器、切分、embedding、RAG/Agent准确率和Java整链。

原文件未推送，离线复现依赖本机缓存；重抓网页变动会产生不同hash，不能声称URL即可复现旧字节。规格和来源不要求执行代码测试，后续解析器需先失败测试。提交/正常推送确认后才进入下一子步；提交SHA在收口消息提供。
