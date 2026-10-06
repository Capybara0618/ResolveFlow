# 原始政策文档入库：实施记录

## 2026-10-06 第一批：规格和官方来源

实施[规格](../../docs/policy-document-ingestion.md)、[来源清单](../../evals/policy-documents-v1/sources.json)及冻结manifest。沿用主分支、依赖锁、生产政策/旧评测和四个原有脏文件，不启动数据库写入/付费模型/后台页面。

实际核验官方京东服务总则/数码说明、小米有品自营规则、宜家使用条款；web打开四页均可读，另外Python urllib直接抓取四页HTTP200，原始字节82547/79625/19405/143668，共325245字节。存于忽略目录`tmp/policy-documents-v1`，非敏感HTTP标题/URL/hash元数据同目录保存。JD字节按GB18030解码，MI/IKEA为UTF-8；HTMLParser只读观察确认正文容器分别为div.content/div#wrap/div.bcms-rich-text__content。

只读源码核验确认原导入先YAML进入Java再经内部API供Python建索引；本批不是从真实商家获得的政策。公开材料含范围外换货/维修/运费/发票等说明，全部为外部参考，不映射生产商家，不给予Agent新增动作。

实际命令：PowerShell通过`agent/.venv/Scripts/python.exe -`运行urllib Request/urlopen（25秒超时、4MB读取限制），写原字节和SHA-256；第二条命令用HTMLParser查看meta及正文容器。来源JSON/manifest/hash/缓存大小/严格解码/文档链接用标准库检查，`git diff --check`检查格式。来源无法访问/抓取失败0；未测正式解析器、切分、embedding、RAG/Agent准确率和Java整链。

原文件未推送，离线复现依赖本机缓存；重抓网页变动会产生不同hash，不能声称URL即可复现旧字节。规格和来源不要求执行代码测试，后续解析器需先失败测试。提交/正常推送确认后才进入下一子步；提交SHA在收口消息提供。

第一子步206c5cd已普通push到origin/main并ls-remote核实。

## 2026-10-06 第二批子步：离线结构解析

新增`scripts/policy_documents.py`与通用结构测试，标准库HTMLParser/urllib，无依赖锁或agent/src改动。支持明确正文定位、UTF-8/GB18030严格解码、来源hash绑定、章节/列表、表格行列与合并属性、原文行列/字符区间/片段hash。显式抓取模式限制HTTPS及同host重定向、HTTP200 HTML、25秒超时、4MiB响应；缓存和输出不可覆盖，抓取hash漂移明确失败。默认纯离线，无模型/数据库调用。源码/配置hash进入结果，结果统一PENDING_REVIEW/indexable=false。

先运行新测试：缺模块导致collection error，退出1。第一实现11 failed/12 passed，根因是方法名offset撞到HTMLParser已有整数属性，改为source_offset后23通过；不是针对政策文本的补丁。首次Ruff有6项（导入排序、测试长行、网络调用审计），格式修复并注释已验证HTTPS的Request后通过。实际网页检查补充加粗标题/非th表头的通用待审提示、路径读入前校验和源码指纹；最终新增32项全部通过。

集中命令：

```powershell
agent/.venv/Scripts/python.exe -m ruff format --config agent/pyproject.toml scripts/policy_documents.py agent/tests/unit/test_policy_documents.py
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_documents.py agent/tests/unit/test_policy_documents.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_documents.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_live_baseline_merge.py -q --basetemp tmp/policy-documents-tests-batch --junitxml reports/policy-document-ingestion/tests.xml
agent/.venv/Scripts/python.exe scripts/policy_documents.py --output tmp/policy-documents-v1/parsed-final.json
```

最终66 passed/0 skipped（32新解析＋34既有切分/探针/聚合），Ruff通过，[JUnit](tests.xml)。实际离线四页解析成功、来源manifest/原文hash全部一致；246块行/列/字符区间/原片段hash逐一核验，结构统计见[机器报告](structure-summary.json)。完整原文/解析正文仅在忽略缓存，不提交版权全文。

| 来源 | 结构块 | 表格 | 需要确认的加粗标题候选 |
|---|---:|---:|---:|
| 京东总则 | 21 | 4行×6格 | 3 |
| 京东数码 | 24 | 无 | 4 |
| 小米有品 | 87 | 3行×5格 | 7 |
| 宜家条款 | 114 | 无 | 6 |

京东总则无h1-h6章节；小米表头使用普通td，加粗标题不是可靠章节标签。原文件保留这些实际问题，不把格式疑点自动改成业务事实；JD正文容器还有面包屑/下载入口，尚未充分清洁。宜家包含日期文字，但来源effective_from仍null，须确认该日期适用范围，不能自动认定是售后政策生效日期。

重复执行同一`--output ...parsed-final.json`实际退出1/FileExistsError，原输出hash未变，属于预期覆盖拒绝。新增来源/URL/商家/路径/编码异常、来源manifest漂移、空正文、可选闭合、脚本/隐藏文本、章节例外、表格合并、跨host重定向均有组件测试；不会执行网页指令，也不因未知字节进行replace解码。

未运行/未实现：正式条款语义确认、合并表格逻辑网格展开、PDF/OCR/动态页面、新语料向量化/检索对照、独立Gold、全Agent/Java/网页验收、生产政策导入或索引重建。解析4页仅证明结构处理探针，准确率null、独立Gold0；“原始文档→业务政策→可验证检索”整批尚未完成。下一步处理正文边界/章节与必要例外关系并生成待审条款，再新实验语料检索基线；无自动公开政策采用或收费调用。
