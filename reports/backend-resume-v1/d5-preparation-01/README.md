# D5：隔离数据与 SQL 计量准备

2026-10-26 开始，2026-10-27 Docker 恢复后核验。此小步未产生正式 HTTP 性能指标，不替代 48 个正常窗口、15 个故障窗口或 R120。

## 已验证

- 隔离 run `56a1dc2143e44062bda79849e82cac3c`，仅本轮带归属标签的 MySQL/Redis；未启动 MQ、Agent 或退款执行器，原业务卷保留。
- D0 原始 JAR 与 D4 候选 JAR 逐字节复制并解包原 class/lib，用独立 `D5Probe` 启动；应用代码不重新编译。JDBC execute 计数包含身份、epoch 与页面查询，SQL inflight 与页面加载事件分别记录。探针只绑定 loopback，控制请求校验本轮 ID，不打入生产 JAR。
- seed42：20000 工单（4000 待审）、10000 已付订单、2000 未付草稿、30 商品/45 SKU/6000 条评价。外键及 CHECK 保持启用，金额差额与评价签收资格异常均为 0。它们是直接构造的合成读模型，未执行真实支付或退款；待支付到期时间专供稳定查询，不代表创建接口生成的数据。
- 生成器已有开始标记，拒绝覆盖或重播。数据 SQL/oracle/hash 在本轮 tmp 留存，Docker 重启后实际工单 20000、评价 6000 保持。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_d5_runtime.py -q`：4 passed；三个新 Python 文件 Ruff 通过。

## 证据与失败

本机忽略目录 `tmp/backend-resume-v1/56a1dc2143e44062bda79849e82cac3c` 留有 `d5-builds.json`、`dataset-started.json`、`dataset.sql`、`dataset-oracle.json`、`dataset-checked.json`、探针 class/源快照及进程日志。数据 SQL SHA256 `3ae0335611ea636b3414caf5d82cefec81142391886589564eab5c000795b337`，oracle SHA256 `6fed2d352b6055673bca7661fe43ee84c75841e45141149f33c692eb0e68475f`。

首次 Commerce 启动/计量成功，Case 因本机 SocketException（No buffer space available）启动失败；同一冻结构建单独重试成功，探针记录 23 条启动 SQL。尚未证实底层原因，不归因为外网。首次失败日志保留；没有正式轮被重跑。Docker 重启后按归属恢复原容器，未重新生成数据。恢复检查中一次误用旧表名的只读等待未成功，随后按实际 aftersale_case 表核验。

## 下一小步

实现并冒烟固定流量、逐请求正确性、双 Commerce 分流及故障注入、离线审计；修正开发探针门控的多加载标记语义，再冻结新的执行器/探针版本。当前源快照不覆盖。完成正式 manifest 后才一次执行约定矩阵，错误、超时、拒绝和未触发故障都保留分母。简历第 4/5 条及 Agent/PDF 冻结不动。

## 固定流量与离线评分小步（2026-10-27）

新增 backend_d5_http.py，实际 Gateway 外层 aiohttp 持久连接、并发固定在途、3秒超时/无重试；每请求实际耗时、状态、完整响应规范化hash及唯一序号留 gzip。离线从逐请求重算最近秩分位数、正确/失败分母；伪造成功、丢失/重复请求、缩短窗口均拒绝。合成身份仍通过正式持久账号和版本校验，令牌只在内存，未计登录时间。

候选无缓存先用独立SQL/生成器事实验证183请求变体，再冻结完整响应hash；工作台两店/下一页、50买家×3状态组合（固定一半筛店）、30评价页。P2的500槽中74空页，三个profile流量分别80/10/10、60/20/20、80/20。完整旧构建比较尚未运行，这份开发oracle不能当A/B一致性证明。

实际命令：模块 freeze_requests 生成 http-oracle-development-01.json；window+score 对P1/P2/P3各10并发2秒，分别226/346/1153，共1725请求全部200且投影一致。只是短开发冒烟，p95不作正式收益。9项单元（runtime4/http5）通过，两模块及测试Ruff通过；真实HTTP反例检查500错误保留实际延迟，不填配置超时值。

门控改为每gate仅首个加载写entered标记，多个加载共享等待，避免无锁组因重复CREATE_NEW误报异常；原探针快照保留，新v2实际编译并启动两服务及Gateway通过。运行器增加独立commerce2、可指定自有Redis/Commerce代理端口与按marker归属停单进程，双实例/代理正式接线尚待下步。0模型/退款执行。

## 双实例与正式入口接线（2026-10-27）

旧Commerce A重新启动后183完整投影与开发候选oracle全部一致。新增 backend_d5_relay.py 为自有连接提供固定双实例HTTP轮转及Redis drop/stall/normal控制；真实网络反例验证分流2/2、未授权控制403、暂停转发/恢复和断连EOF。backend_d5_normal.py固定48窗口及ABC/BCA/CAB、AB/BA/AB顺序，正式30秒预热/60秒采样，逐窗口独立namespace、冷读、warmup、SQL前后快照、路由计数及hash；已开始未完成窗口拒绝重做。

实际 `python -m evaluation.backend_d5_normal smoke --run-id 56a1dc2143e44062bda79849e82cac3c --cohort normal-development-01`：八构建/开关组合各10并发、1秒预热+2秒采样全部正确；数值见 normal-development-summary.json，只属开发接线，不宣称性能改善。正式入口和评分器hash/运行端口/探针版本在freeze中绑定，运行前逐项复核，后续新增故障模块使用独立manifest。

新v3探针仅在开启事件时记录真实RLock tryLock等待/结果、owns与unlock，不改原调用参数或业务结果。实际双Commerce受控冷态10请求为1个200+9个503（首次客户端冷启动约1秒），事件仅一次页面加载；释放后10秒预热1480/1480正确、2秒采样147/147正确。门控事件和正式热态指标分开，503保留。v1/v2构建与记录不覆盖。11单元/Ruff通过，0收费/退款执行。正式48窗口/15故障/R120仍未开始。

## 故障执行器的离线准备（2026-10-27，真实接线待正常矩阵结束）

正常48窗已经按normal-v1冻结入口运行，执行期间不改其绑定的源码/数据/参数。新增独立 backend_d5_faults.py 固定15窗（32并发、10秒预热/30秒采样）；backend_d5_rebuild.py/support/audit 为R120准备双实例分流、门控、实际PID暂停/终止、合法回复及恢复证据、逐请求start/end日志和离线重算。新增9项离线单元通过，含120/15分母及顺序、真实重叠而非两节点峰值相加、缺end必须有终止证据、只读Redis观察器、伪成功/假故障/未决请求拒绝；新增源码Ruff通过。此小步只证明离线结构，未编译或启动新SQL写前探针，未执行15窗或R120。

R探针将从未改动的v3源另派生一份只在事件开启时写SQL-execute记录的评测class；每条关闭文件，覆盖JVM进程终止，不承诺掉电持久。原v1/v2/v3快照保持，R源/class再冻结。R CLI拒绝在normal-v1完整48窗审计前切换探针或添加读模型，避免污染当前压测。随后先独立开发样本验证，再一次性准备R120全部新产品/epoch/独立已签收行，SQL与fixture清单冻结后才开正式轮；不在正式轮临时生成或重播样本，也不执行资金provider。

R02异常明确发生在查询快照完成后，不称数据库SQL异常；R04加载窗口包含人为暂停，不称同时SQL执行峰值。中途未触发/失败轮保留，不能变更同一轮参数重跑；5秒恢复包含实际解除/终止起点，10次后续读取单列，拒绝/错误与重建降幅共同报告。所有新工具仍待真实接线验收，当前运行的正常窗不以它们评分。

## 计量边界与恢复起点修正（2026-10-27）

正常v3不改。核对已完成P1-r0-c10-A：4143请求、实际JDBC execute 16572（每请求4），rows_returned仅4143；原因是MyBatis的execute()+getResultSet路径未被行计数代理覆盖，当前rows_returned只覆盖executeQuery返回的ResultSet。这一字段不能称总返回行或扫描行，正式SQL次数与HTTP指标不受影响；扫描/loops仍看D3/D4已有EXPLAIN证据。不为补行计量改正在运行的探针或重跑窗口。

独立故障执行器在正式冻结前将恢复起点钉在代理实际normal事件时间，包含控制应答到观察器启动的间隔；新增真实HTTP单元验证起点已过去2秒会计入恢复耗时，超过5秒后成功的后续请求不能反填恢复成功。该目标1项通过、相关两文件Ruff通过；累计21项不同D5离线/网络单元，真实15窗/R120仍待接线。故障窗口若返回未约定的HTTP500等状态不得只因后续恢复就计通过。

故障开发样本计划补齐真实TTL和超时：R开发16条件=六场景B/C首轮12条件+R01真实30秒到期/N30两条件+R06命令超时/N30两条件，独立于正式R120。避免仅用冷态/断连冒烟后直接进入到期/超时正式轮；新增断言并目标运行 `pytest .../test_backend_d5_rebuild.py -q -k 120_rebuild`：1 passed/8 deselected，相关Ruff通过（仍累计21不同检查）。尚未实际创建这些开发样本或运行新探针；正常48窗继续沿原manifest。

开发cohort隔离反例：先用两份临时目录/SQL响应桩调用开发数据准备，新批次仍生成相同产品ID，目标检查按预期1 failed（8.11秒，日志tmp/backend-d5-cohort-identity-first-fail.log），未访问真实数据库。修正UUID标签加入data-cohort、gate标记绑定完整cohort/round路径；新两批各56产品ID完全不重合、同轮gate在不同批次不同，目标1 passed/9 deselected及Ruff通过（累计22不同检查）。原开始/完整标记仍拒绝同批重复执行，不借新cohort重跑正式失败；本修正只在正式故障冻结前开发，normal-v1不变。
