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

## 2026-10-06 正文边界、章节草稿与编码长度诊断

新增[结构配置](../../evals/policy-structure-v1/README.md)、`scripts/policy_drafts.py`及26项测试。旧来源manifest/原文hash、原解析器、旧报告和生产索引均不变；`profiles.json`另冻为独立manifest，绑定原来源manifest。每个章节/表头标记绑定block ID、文本hash和原片段hash，不按query/案例或最终动作分支。

JD从.content缩到.contxt，原21/24块变20/21块；4个排除块分别是面包屑/下载入口及正文外“猜你感兴趣”的推荐链接，完整原文件仍保留。小米87块、宜家114块不删，合计242块。非售后章节不按关键词过滤，以便未来测范围/负例。每块唯一直接章节归属、原文顺序、检索与完整依据hash均核验。

补齐非h标签标题的显式结构草稿及小米5个表头单元格解释，保留original_header/header_origin；不是人工确认的Gold。JD总则与附注/排除条件、数码条件与注意事项、小米条件/排除项及地域/适用范围作为候选关系；闭包有界，跨主体/未知章节拒绝，双向关联不重复。原解析告警保留，JD仍有1段加粗引言候选未当标题。输出统一PENDING_HUMAN_REVIEW/publishable=false/indexable=false，未运行Java导入。

本地实测BGE固定revision tokenizer/max_seq_length=512，包括特殊token、truncation=false；完整章节29个候选中16个超限。该结果证明“整章节直接向量化”会出现截断风险，不能把章节草稿当最终chunk。最长宜家根文档10039 token；章节检索子块与完整依据分离需下一步实现，当前没有向量化这些超限候选。

| 来源 | 正文块 | 章节候选 | 超512 token | 最长候选 |
|---|---:|---:|---:|---:|
| 京东总则 | 20 | 3 | 1 | 991 |
| 京东数码 | 21 | 5 | 2 | 951 |
| 小米有品 | 87 | 11 | 6 | 3816 |
| 宜家条款 | 114 | 10 | 7 | 10039 |

实际命令：

```powershell
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_drafts.py agent/tests/unit/test_policy_drafts.py --fix
agent/.venv/Scripts/python.exe -m ruff format --config agent/pyproject.toml scripts/policy_drafts.py agent/tests/unit/test_policy_drafts.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_drafts.py agent/tests/unit/test_policy_documents.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_live_baseline_merge.py -q --basetemp tmp/policy-drafts-tests-final --junitxml reports/policy-document-ingestion/draft-tests.xml
agent/.venv/Scripts/python.exe scripts/policy_drafts.py --audit-encoder --output tmp/policy-documents-v1/drafts-audited.json
```

先失败为新模块不存在/collection error；实现后18 passed，首次Ruff仅导入排序1项，修正后通过。补实际token审计及manifest/缓存漂移测试后，最终92 passed/0 skipped（26新增＋前批66），[JUnit](draft-tests.xml)。实际四页重解析和草稿构建、原来源hash、结构配置hash、唯一归属/上下文引用/文本hash校验通过，[机器报告](draft-summary.json)记录源码/配置/输出hash及长度。Tokenizer一次长序列警告为预期诊断，不是前向编码错误；不截断、不运行超长embedding前向。

未运行：独立人审/商家政策采用、长章节子块编码与新索引、query Gold/相关性和检索对照、整体Agent/Java/浏览器。新增收费调用0，未重启服务/写业务库，依赖锁及原四脏文件保留。结构关系可能宽泛/遗漏，不保证“已找齐全部必要例外”；待审不阻止做长度可控的实验，但不能当生产政策发布。下一步按encoder实际限制拆分检索子块，完整依据保留父节/候选关联且测上下文体积，再建立新语料召回基线。


## 2026-10-06 检索子块与本地向量探针

新增`scripts/policy_chunks.py`及29项通用组件测试；本批复用冻结原文/草稿/encoder，未改生产代码、旧Gold、依赖或数据库。子块按直接章节块一次构建，真实token/offset切分并复核每个字符串，长段落无损；简单表格每行重复列名，保留原表/行/定位/hash。完整依据单独绑定章节及候选关联；重复上下文身份、重复章节映射、来源/hash错误明确拒绝。

先失败：新模块不存在，collection error/退出1。初次实现7 failed/12 passed，Counter(dict)误把字典值作为计数，修正为Counter(keys)后19通过；Ruff闭包B023改为显式参数函数，未忽略诊断。追加歧义绑定负测后2 failed/27 passed（重复章节映射和context ID未拒绝），补通用唯一性校验后29通过。不是对query或退款场景定制答案。

实际集中命令：

```powershell
agent/.venv/Scripts/python.exe -m ruff format --config agent/pyproject.toml scripts/policy_chunks.py agent/tests/unit/test_policy_chunks.py
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_chunks.py agent/tests/unit/test_policy_chunks.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_chunks.py agent/tests/unit/test_policy_drafts.py agent/tests/unit/test_policy_documents.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_live_baseline_merge.py -q --basetemp tmp/policy-chunks-tests-final --junitxml reports/policy-document-ingestion/child-tests.xml
agent/.venv/Scripts/python.exe scripts/policy_chunks.py --max-tokens 384 --embed --output tmp/policy-documents-v1/children-final.json
```

最终121 passed/0 skipped（29新＋前批92），Ruff通过，[JUnit](child-tests.xml)。实际本地BGE revision7999e1d3359715c523056ef9478215996d62a620、encoder512、候选目标384；得到66向量/66子块，最长383 token、超限0。此前完整章候选16/29超512与当前子块0/66超限是不同粒度的长度诊断，不能称召回质量提升。

| 来源 | 原文块 | 检索子块 | 最大token | 最大完整依据字数 |
|---|---:|---:|---:|---:|
| 京东总则 | 20 | 4 | 318 | 1076 |
| 京东数码 | 21 | 7 | 357 | 1003 |
| 小米有品 | 87 | 20 | 383 | 4043 |
| 宜家条款 | 114 | 35 | 382 | 10513 |

额外以`agent/.venv/Scripts/python.exe -`执行标准库＋既有本地embedder只读核验，输出[机器报告](child-summary.json)：当前源码/原草稿/output SHA一致；242块的247表示（含7表格行）逐片段区间连续、文本重组/原文定位/hash一致，无丢失或重复。每个实际chunk按不截断tokenizer重新计数；66×512维向量有限非零，范数0.999999928–1.000000116。每个chunk回查完整依据并检查主体/快照/hash。

完整依据29份；8000字符探针上限下1份宜家根上下文10513字超限，关联1个chunk。实际返回CONTEXT_TOO_LARGE、complete=false/text=null及完整块引用，没有截断导出。8000仅探针字符参数，非聊天模型token预算、非生产限制；未把10513字正文送入LLM，也未证明全部必要关系语义正确。

同一只读命令将机器报告所列4条CODEX_SYNTHETIC_SMOKE_NOT_GOLD问法经本地模型向量化，先按EXTERNAL主体过滤再exact cosine前2。4次/8命中0跨主体，保存query/score/chunk/context ID，未保存版权正文。required_chunk_ids全null，独立审查0，retrieval_accuracy=null；这只是向量/检索/回查接线探针，不算相关性或多依据覆盖通过，也不是来自真实客户。两页京东同一来源家族，不冒充独立商家样本。

实际还跑过初版`children-v1.json`，绑定旧的中间构建器hash，仅作为本机中间产物；最终报告绑定`children-final.json`，不混用。对final重复执行相同CLI实际FileExistsError/退出1，原输出SHA未变，属于预期覆盖拒绝。Tokenizer在计数待拆长段落时报告537>512警告，前向embedding仅接收已验证≤384的最终子块；该警告不是对超长段落执行向量化。

未运行：独立Gold/商家采用、正式召回准确率或前后算法受控比较、LLM上下文装配/整体Agent、Java/浏览器、生产政策发布/索引重建/服务重启。收费调用0、业务写入0。下一步补新语料逐query必要依据/例外/无答案标注与固定检索基线，之后按失败选择表示/query/排序调整；384尚未证实最优，父节过大/关联宽泛及行切分语义需评测。旧四脏文件和草图日志不夹带。


## 2026-10-06 新语料逐query待审标注与检索基线

新增[policy-query-v1](../../evals/policy-query-v1/README.md)：29条问题（复用11官方FAQ＋18作者来源感知合成诊断）、41原文依据原子，在本轮排名前冻结queries/evidence与原草稿/子块/FAQ manifest hash。所有正式标签null、独立复核0；草稿17可答/1部分/3须澄清/8语料无答案，不冒充独立Gold、客户日志或测试集。结构问题覆盖定作/激活/食品例外、质量与无理由物流费、总则与类目时限、地域/销售主体/线上线下渠道、退款办理与到账及相似无关材料。

新增`scripts/policy_query_eval.py`＋27通用测试：来源快照/证据区间/hash/数量冻结校验，原始block/表格row/span计分，部分片段与重复重叠不刷覆盖；dense和BM25先主体+快照硬过滤再排名。直接与父节扩展覆盖分开，回查按排名贪心/重复ID或相同payload去重，总字符预算包括分隔符，超限不作为已交付证据；不同上下文的部分重叠仍可能保留，暂非最优选择。正式指标只用独立APPROVED可答标签，无答案/缺事实不空集合通过，拒答质量未实现。

实际命令：

```powershell
agent/.venv/Scripts/python.exe -m ruff format --config agent/pyproject.toml scripts/policy_query_eval.py agent/tests/unit/test_policy_query_eval.py
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_query_eval.py agent/tests/unit/test_policy_query_eval.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_query_eval.py agent/tests/unit/test_policy_chunks.py agent/tests/unit/test_policy_drafts.py agent/tests/unit/test_policy_documents.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_live_baseline_merge.py -q --basetemp tmp/policy-query-tests-final --junitxml reports/policy-document-ingestion/query-tests.xml
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --prepare-review --output tmp/policy-documents-v1/query-review-v1.json
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --context-chars 8000 --output reports/policy-document-ingestion/query-baseline.json
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --require-reviewed --output tmp/policy-documents-v1/reviewed-gate.json
```

先失败为缺模块collection error/退出1；初次实现13测试通过，首次Ruff有导入排序和多语句/长行共15项，格式化修正；扩充总预算/同payload去重/独立标签与草稿分离/原子漂移等后27通过，Ruff最终通过。最终集中148 passed/0 skipped（27新增＋前批121），[JUnit](query-tests.xml)。质量门禁命令实际退出1/independent labels pending，未创建报告、未运行embedding，属于预期待审拒绝；不得记为正式质量通过。

实际本地BGE对29短问题向量化，dense/BM25共58查询记录，[逐问报告](query-baseline.json)保存排名/分数/源快照/缺依据/导出体积/源码与输入hash/依赖版本，没有原政策全文。所有调用范围通过硬过滤与计分前复核，无跨主体/快照。BM25在过滤后的同主体语料计算统计；两方法同query/语料/表示/预算，未改生产排名。当前无语义判定/拒答阈值，8条无答案仍会返回近邻，不能因此称检索器错误接受答案或拒答通过。

以下仅为作者草稿诊断计数，分母17条draft ANSWERABLE，不是正式召回/准确率：

| 路径 | 直接找齐前2 | 直接找齐前5 | 扩展后找齐前2 | 扩展后找齐前5 | 全29问前5平均导出字符 |
|---|---:|---:|---:|---:|---:|
| dense | 5/17 | 9/17 | 10/17 | 16/17 | 3446.79 |
| BM25 | 7/17 | 12/17 | 11/17 | 17/17 | 3425.72 |

两种方法前5均出现1次整context预算拒绝，体积未超过8000总字符。正式all_required_direct/context指标和abstention_accuracy全部null；没有独立人审、没有holdout。FAQ中草稿可答仅1条，另一条部分可答，绝大多数17分母来自来源感知合成问题，不能据此裁定BM25优于dense的真实用户效果，也不能称RAG已优化完成。

学习归因：直接覆盖低、父节扩展高，说明索引表示/跨章节依据与返回策略是不同问题；返回较大父节可能掩盖检索缺口，必须并报体积。S:MI04要求并列核对“赠品不完整”和“赠品扣款”，dense前5扩展仍缺一个不办理条款；这只是待审的跨章节关系诊断，不补按case ID的关系或query补丁。其他前2缺口包括日期多文档、类目限制与质量/运费条件；先复核Gold/适用性再决定通用表示或关联策略。BM25本轮较高草稿计数照实保留，不为了展示dense更好而删失败或改标签。

本机无排名复核包包含全部4文件/242块，隐去draft/排名，只存忽略tmp；不是仅让复核者在作者预选41原子中挑选。解析结构仍为作者草稿，需结合原HTML。人工确认必须另冻新版本并真实归因；文件协议无法自动认证复核者身份。重复CLI输出实际拒绝覆盖，原报告hash不变。原全文、生产索引、旧评测/Gold/原四脏文件不改，付费LLM0、生产写入0。

未运行：独立相关性/适用性人审、拒答与回答语义评测、算法优化后受控提升、生产LLM上下文/整体Agent/Java/网页/服务重启。后续按独立标签和失败类别比较标题/表格表示、跨章节必要依据及query；不默认加hybrid/rerank，不追单例满分。当前长度处理＋可追溯逐query诊断已具备，RAG质量结论仍待审。


## 2026-10-06 标题表示与原文块并集受控实验

按用户继续指示完成[固定实验](../../evals/policy-representation-v1/README.md)，不等待标签时伪造独立人审，而是明确按作者草稿进行机制诊断。新manifest在标题排名前冻结旧query/基线/源码，旧policy-query-v1和所有Gold/原文/子块/生产索引不改；body/完整章节路径两种表示、dense/BM25两路径及两种装配，全部同29问/17草稿可答分母，模型/依赖/8000总内容字符固定。

新增`scripts/policy_representation_eval.py`及22通用测试。前缀标题实际token审计，超encoder限制在embedding前明确失败，无截断/隐式回退；来源碎片坐标保持原body，不将标题自身作为原文证据。原文块装配验证context与原块完整文本/hash/主体/快照一致；source/rawsha/block身份去重，单文件原文顺序保留，不跨版本合并。context必要块作为不可拆整体准入，部分新增例外放不下则整份拒绝，不返回半套依据。

实际命令：

```powershell
agent/.venv/Scripts/python.exe -m ruff format --config agent/pyproject.toml scripts/policy_representation_eval.py agent/tests/unit/test_policy_representation_eval.py
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_representation_eval.py agent/tests/unit/test_policy_representation_eval.py
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_representation_eval.py agent/tests/unit/test_policy_query_eval.py agent/tests/unit/test_policy_chunks.py agent/tests/unit/test_policy_drafts.py agent/tests/unit/test_policy_documents.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_live_baseline_merge.py -q --basetemp tmp/policy-representation-tests-final --junitxml reports/policy-document-ingestion/representation-tests.xml
agent/.venv/Scripts/python.exe scripts/policy_representation_eval.py --output reports/policy-document-ingestion/representation-experiment.json --cache-output tmp/policy-documents-v1/representation-v1.json
```

先失败缺新模块collection error/退出1；实现后11通过，首轮Ruff导入1项、扩充测试后2项排序均修复，最终22新项。集中170 passed/0 skipped（22新增＋前批148），Ruff通过，[JUnit](representation-tests.xml)。没有实施失败后按问题ID修订算法；通用反例测试主动证明贪心准入并非覆盖单调保证。

[实际116条记录](representation-experiment.json)先复现body/dense与BM25各29的排名/分数（绝对容差1e-6）/计分/体积，58旧记录全部一致。body最长383/总16130 encoder token；完整标题路径最长444/总18106，66新向量全部低于512，无encoder警告或默认截断。query仍29个原问法；标题只来自冻结章节路径，不额外生成关键词或按场景改写。

下表分母17均为draft ANSWERABLE，独立Gold0，正式质量null；并集覆盖本轮与完整context相同：

| 表示/路径 | 直接前2/5找齐 | 完整context前2/5找齐 | 前5平均原context字数 | 前5平均原文块并集字数 |
|---|---|---|---:|---:|
| body/dense | 5/9 | 10/16 | 3446.79 | 2876.97 |
| body/BM25 | 7/12 | 11/17 | 3425.72 | 2888.93 |
| title_path/dense | 6/7 | 11/15 | 3279.72 | 2757.69 |
| title_path/BM25 | 6/12 | 11/17 | 3351.93 | 2899.97 |

决定：完整标题路径未通过诊断，尤其dense前5退化，保留body、不部署；前2少量改善不能抵消前5退化，也不能证明真实效果。正文并集前5平均字数降低dense16.53%/BM2515.67%，是去重的固定样本效果，不是LLM token节约或答案质量改善。

另用`agent/.venv/Scripts/python.exe -`读取已冻报告和本机cache，独立重算旧context准入与新原块准入、文本sha/主体快照/完整引用，输出[232前缀源块审计](representation-audit.json)：116记录均无基线来源块丢失、草稿缺依据集合变化0、所有已接纳context所需块全在导出集合、内容总字符均≤8000。body/dense前5为23问减少/6相同；body/BM25为21减少/7相同/1增加。S:IK04在BM25（两表示）5913→7708字，因新准入额外章节，并未增加必要依据覆盖；去重不是相关性过滤，不能忽略这个增加例或称噪音已去掉。

经验与取舍：检索加元数据可能稀释细则而非提高召回，完整路径的根/父标题有重复泛化词；这只是失败解释假说，未做叶标题/权重的新受控证明，不继续追参数或补两条题。上下文去重只保证单个已接纳context完整；释放空间会改变贪心准入顺序，通用测试证明可能新增早期context而挡住后面的context。本轮无损不能当普遍定理；若强调相同信息集合，应先固定context选择，再做来源块无损表达的新实验。

全文/新向量保存在忽略cache，公开报告不含原政策正文；脚本强制full cache位于tmp、报告/cache不同且不能覆盖。实际同路径重复命令退出1/FileExistsError，报告/cache hash仍一致，属于预期覆盖拒绝。旧来源/Gold/解析器/依赖/生产代码均不改；付费LLM0、生产写入0、无部署或服务重启。未运行独立人审、真实客户/holdout相关性、LLM引用与token装配、拒答/整体Agent/Java/网页。后续先确认必要依据与适用性；可独立验证context选择与无损装配，当前标题试验失败和去重边界保留，不自动扩大算法栈或收费。
