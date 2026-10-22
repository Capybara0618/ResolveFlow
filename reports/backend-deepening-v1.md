# 后端深化验证记录

## B2.4b 账号原子写入限流（2026-10-22）

B2.4a 0bebd5d已普通push核实。Case在鉴权/角色检查后、Commerce调用前，按已认证账号+WRITE/REPLY动作执行Redis Lua原子INCR/EXPIRE，首请求起60秒内各动作最多6次。key摘要化账号，不接受客户端归属或限流键；Redis重启可清空窗口，业务唯一性仍由MySQL控制。超过限额429/Retry-After60秒，Redis异常503/Retry-After1秒且可重试，不退化为无限写入。正式本机/core Compose启用，单测默认可禁用。

新3真实Redis测试对空限流骨架先全部失败；实现后Redis3项+既有评价HTTP3项共6通过（38.086秒）。两个limiter实例12并发合计6放行，动作/账号相互隔离，所有窗口有TTL；CLIENT PAUSE2000ms时100ms命令超时，1200ms内明确拒绝。补HTTP429/503必须在Commerce写入前返回的断言后，3实Redis+5HTTP=8通过（33.899秒）。Java21命令 `./mvnw.cmd -B -pl case-service -am spotless:apply '-DspotlessFiles=.*ProductReviewApiTest.java' test '-Dtest=ReviewWriteLimiterRedisTest,ProductReviewApiTest' '-Dsurefire.failIfNoSpecifiedTests=false'`；新limiter/RedisTest已在前一步定点格式化。

driver/project运行配置测试38通过（0.43秒）、core Compose config及diff检查通过。未跑付费模型/正式数据迁移，当前B2接口/三端UI/缓存/限流的工程验证已具备，正式网页和真实Case→Commerce集中验收仍待B3后独立环境完成。

## B2.4a 评价首页/评分 Redis 缓存（2026-10-22）

B2.3c 0c5a26b已普通push核实。Commerce复用Case已经使用的Boot Redis starter版本，不换依赖锁；独立缓存服务在事务外访问Redis，首个默认10条页面和评分一起缓存30秒。每次先从MySQL验证商品公开可见性及epoch；修改/回复与epoch同事务。key含product/epoch，迟到旧填充不能覆盖新代。更多页/自定义页大小直接数据库；所有数据库入口共享8并发/100ms门控，缓存异常回源、过载503，缓存不承担资格/金额权限。

新2缓存测试对未缓存骨架先失败，实施后缓存/领域/HTTP12通过（36.016秒）。补真实MySQL+Redis代际更替、旧代晚写、损坏JSON回源和12并发门控后5项通过；再加真实Redis CLIENT PAUSE2000ms，100ms命令timeout使评价仍从DB返回并在1200ms内完成，最终3单测+3实Redis/实MySQL=6通过（29.284秒）。Redis容器仅本测试独有，不FLUSH共享数据。所有缓存命中仍含一次epoch数据库读取，不宣称DB查询归零/延迟提升。

正式本机Commerce启动增加PRODUCT_REVIEW_CACHE_ENABLED/独立56380 Redis，core Compose设置Redis内部地址和依赖。运行接线新断言先缺环境变量失败，补后driver/project两文件38通过（0.32秒）；core Compose config通过，定点Spotless及diff检查通过。Ruff仍沿用前述旧脚本19项基线，不称全仓全绿。尚未部署正式服务或压测，未调用模型。接下来B2.4b账号写入限流。

## B2.3c 商家评价与回复（2026-10-22）

B2.3b 64ed751已普通push核实。统一商家导航新增商品评价，显示本店反馈和公开回复；不提供删除/改评分入口。回复绑定原review_id/version，冲突后保留本地回复，用受商家范围约束的before=id+1/limit1定位原评价，展示买家当前文字后再提交；未知响应冻结原目标/原内容并支持确认。写入向父工作台发working，账号变化/卸载忽略旧读取。

新3商家组件测试先全失败，实现后 `pnpm --dir web test -- merchant-reviews.spec.ts admin-workspace.spec.ts` 8通过、web build通过。全前端首214通过/1失败，原因是foundation精确导航仍6项；在原精确断言加入商品评价，并新增导航进入/真实客户端请求路径断言，非删除旧断言。最后 `pnpm --dir web test` 30文件215通过（6.31秒），git diff/cached通过。尚无正式业务网页实拍，预期图与组件mock结果分开。接下来B2.4评分缓存和账号限流。

## B2.3b 买家订单行评价编辑（2026-10-22）

B2.3a 7fa5646已普通push核实。已付款订单提供按行“评价商品”入口，点击才读取本人资格，避免订单打开就增加逐行评价查询；未签收展示后端拒绝原因。编辑器只提交分数/文字/原版本，保存后展示服务器内容；409保留本地文字并冻结提交，明确读最新记录后展示当前内容供核对；网络/5xx保留原请求、冻结输入，可原内容确认或先查当前记录，未确认不显示成功。写入期间阻止父页面导航。

新4组件测试对空组件先全失败。接实现后14通过/3失败，原测试对未attach表单点button未触发原生submit，改为form submit事件验证；增加订单入口按需读取的集成测试后 `pnpm --dir web test -- product-review-editor.spec.ts buyer-orders.spec.ts` 18通过（1.63秒），`pnpm --dir web build` vue-tsc/Vite通过，git diff/cached检查通过。尚未实际浏览器提交评价，不将mock交互当端到端。下一步商家回复界面。

## B2.3a 商品页公开评价（2026-10-22）

B2.2提交5d94d6a首push发生schannel中断，第一次核对远端也空响应；使用命令级HTTP/1.1核对远端仍79ab120、左右1/0后普通重试成功，再ls-remote核实5d94d6a。没有force、改remote或关闭TLS验证。B2.2暂存检查也拦下新JSON fixture的CRLF，提交前统一LF后通过。

新增review-client TS协议和ProductReviews公开组件，商品详情下接入真实API；显示真实均分/星级分布、正文及商家回复、空/错误/分页，Vue文本转义；按商品变化的请求代际阻止迟到覆盖。不在无评价时编造0分，不读取私有订单信息。CSS主事实16px。

新4前端测试对空组件先全部失败；实现后 `pnpm --dir web test -- product-reviews.spec.ts marketplace.spec.ts` 12通过，`pnpm --dir web build` vue-tsc/Vite通过；原样式/其他功能未重做。此次为组件/API mock验证，未称正式浏览器或真实部署验收。下一步B2.3b订单行编辑，B2.3c商家回复，再B2.4 Redis和B3恢复。

## B2.2 评价 HTTP、可信归属与契约（2026-10-22）

B2.1 79ab120已正常push核实。本步纵向接Commerce/Case各5操作，Case派生买家映射/商家身份，私有Commerce路由要求Case部署主体和checkout/fulfillment scope。公共列表允许匿名Case读取；Agent即使持私有scope仍被拒绝。请求额外字段拒绝、rating/version要求整数token；新增严格正文反序列化防数字/布尔值被Jackson静默转为文字。Schema/OpenAPI/共享Wire/fixture/核心路由表同步（Case86/Commerce35/Agent8），公开投影不暴露账号/订单。

新Commerce HTTP3测试先失败（尚无路由）；实现后Commerce领域/HTTP/旧权限18通过。Case首轮8项5通过/3错误，原因是mock先设置通用抛错后用when设置特例触发原桩，改doReturn后8通过（31.906秒），未改权限断言。共享Wire新2测试首1通过/1失败，复现数字正文被转换，严格文本后2通过；最终Java跨shared/commerce/case跑ProductReviewApiTest/ProductReviewWireTest/ProductReviewDatabaseTest，2+10+3=15通过/0跳过（42.717秒）。各相应命令均 `./mvnw.cmd -B -pl <module> -am test '-Dtest=<上述类>' '-Dsurefire.failIfNoSpecifiedTests=false'`，定点Spotless包含本步Java文件。

`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_product_review_contract.py agent/tests/unit/test_contracts_core_routes.py -q` 首82通过/1失败，原LineContext精确字段断言漏已有payment_version/fulfillment字段；核对HEAD与当前LineContext完全相同后，补精确可选字段/状态枚举及双向dependentRequired，不改生产Schema或删除旧断言。最终83通过（59.47秒）；新契约测试Ruff首1长行错误、换行后通过，git diff --check通过。生成附加契约时Windows文本换行曾扩大diff，已恢复原LF，仅追加新组件和路由。fixture索引更新，不改旧冻结数据/hash。

未运行：正式浏览器评价、评分Redis/限流和端到端真实Case→Commerce部署。当前Case HTTP使用边界mock、Commerce HTTP使用真实隔离MySQL，两层证据分开。无模型请求、正式库迁移或收费资源；接下来B2.3双端界面，B2.4评分缓存/限流，B3自动恢复。

## B2.1 评价领域与追加迁移（2026-10-22）

B1.3 0b831fb及文档检查修正65ab7ef均已普通push核实。新增共享ProductReviewWire、Commerce V17追加评价/epoch表、ProductReviewService和真实MySQL领域测试。本人已支付且DELIVERED的订单行可首评；行锁/唯一键确保一行一评；同内容重放、不同内容原版本校验；商家仅回复本店、不能改评分或删除；修改/回复与epoch同事务；公开结果不含订单/账号归属，退款不删除原评价。历史跨店商品映射无效则拒绝首评。

关键6测试对尚未实现的service骨架先全部失败（包含预期异常不符/UnsupportedOperation）；落实领域后 `./mvnw.cmd -B -pl commerce-service -am spotless:apply '-DspotlessFiles=.*ProductReviewWire.java,.*ProductReviewService.java,.*ProductReviewDatabaseTest.java' test '-Dtest=ProductReviewDatabaseTest,ShoppingDatabaseTest,CheckoutPaymentDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false'` 28通过/0失败/0跳过（30.653秒）。再加强epoch重放/失败不增长及跨店SKU映射，用新共7项领域测试复验通过（24.887秒），定点Spotless/diff通过，Java21与隔离MySQL8.4。测试中付款走现有服务，签收/退款账本仅隔离合成夹具设置，不称正式物流/退款闭环新验收。

当前尚无评价HTTP入口或页面，Redis评分/限流未接，不宣称评价端到端完成。未启动正式业务服务、迁移演示库、调用模型或改冻结结果。下一步B2.2接口、严格契约及权限验证。

## B1.3 本机独立 Redis 接线（2026-10-22）

B1.2 9c76b5c 已正常push核实。原本本机 Compose 没有 Redis，Case 被显式禁用缓存；现追加本项目 Redis7.4 服务，loopback56380、无业务卷，与共享56379分离。driver端口守卫/Compose变量、就绪检查、正式status均包含Redis；Case启用缓存并使用本项目端口。未启动正式Java/Agent，旧进程需按正常重启加载，不能称当前页面已验证。

新2测试先全失败（缺redis端口、错误就绪）；实现后相关38项34通过/4失败：两处旧断言仍禁止任何Redis/组件固定9项，改为独立loopback端口、禁止external复用及10组件中必须有Redis；另两项原测试未mock broker tcp导致意外尝试只读共享MySQL见证，被已停止容器拒绝，没有任何写入，补全网络替身。最终 `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_reviewer_demo_driver.py agent/tests/unit/test_project_runtime.py -q` 38通过（0.36秒）。

`docker compose -f infra/compose.reviewer-demo.yaml config --quiet` 通过；只 `up -d redis` 新服务，`exec -T redis redis-cli ping` 返回PONG，再 `stop redis`，未操作其他服务/卷。提交时git diff --check曾指出local-runtime末尾多余空行，PowerShell继续执行而提交0b831fb；紧接独立文档小步去除并重新检查，不称该次初检通过。4文件Ruff检查中reviewer_demo.py有19项历史问题，逐文件用HEAD源码stdin同配置复核：旧19/当前19，其他3文件0/0，无新诊断；未为此改旧脚本无关风格，不称Ruff全绿。下一步B2.1评价领域和实库测试。

## B1.2 商品列表批量读取（2026-10-22）

B1.1 ed53799 已普通push并核实远端。商品列表改为一次商品/店铺查询 + 一次可售SKU批量查询，最多48商品；只读 REPEATABLE_READ 包住两次读取，保留搜索/分页/上下架/规格排序/min价格语义。详情与报价仍读权威事实，不用缓存决定金额。

新 ShoppingBatchDatabaseTest 在真实MySQL上通过Connection代理统计实际prepareStatement：旧实现单商品页3条，预期2而失败；实施后1商品/4商品页均2条，空结果1条，并逐项比对公开详情。未测订单查询或大规模延迟，不把SQL数减少等同p95收益。

java目录相同Java21：`./mvnw.cmd -B -pl commerce-service -am test '-Dtest=ShoppingBatchDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false'` 首次1失败；`./mvnw.cmd -B -pl commerce-service -am spotless:apply '-DspotlessFiles=.*ShoppingService.java,.*ShoppingBatchDatabaseTest.java' test '-Dtest=ShoppingBatchDatabaseTest,ShoppingDatabaseTest,ShoppingApiTest,MultiCheckoutDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false'` 最后4类21通过/0失败/0跳过（29.865秒），git diff --check通过。原四脏文件/正式数据保持，模型调用0。下一步B1.3独立Redis运行接线。

## B1.1 正式工作台缓存（2026-10-22）

文档与三张静态预期图提交 5f55049 已正常推送 origin/main，远端 SHA 已核实。实现根据 docs/backend-deepening-v1.md，保留四个历史脏文件、原数据和冻结实验。未调用模型、未启动正式业务服务。

现象：网页带 view/query/scope，Controller 选择 workspace，原 Redis 缓存只在 list 使用。修复：两条读路径共享 cache-aside 与 8 并发/100ms 回源门控；workspace 键包含人员/商家/阶段/归属/搜索/游标/页大小，先校验权限和游标；缓存读取/写入在只读 REPEATABLE_READ 数据库事务外。旧 list 行为保留。展示缓存仍 2 秒 TTL，写动作继续查权威状态。

关键失败测试先跑：首轮缺嵌套异常 import 编译失败；修正后4项为3失败/1错误，其中游标异常类型断言不符，另3项证明缓存未调用、重复查询和指标缺失。将游标断言纠正为实际 InvalidCursorException，实施缓存并增加事务边界测试后7项通过。真实 Redis 增加正式 workspace 请求命中/筛选与人员隔离检查。

实际环境 Java21（C:/Users/hjn/.jdks/jdk-21.0.12.1+1），Docker Testcontainers 独立 MySQL8.4/Redis7.4，不操作演示数据库。java 目录命令：

```powershell
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
./mvnw.cmd -B -pl case-service -am test '-Dtest=WorkspaceQueueCacheTest' '-Dsurefire.failIfNoSpecifiedTests=false'
./mvnw.cmd -B -pl case-service -am spotless:apply '-DspotlessFiles=.*ReviewQueueService.java,.*WorkspaceQueueCacheTest.java,.*RedisReviewQueueCacheIntegrationTest.java' test '-Dtest=WorkspaceQueueCacheTest,ReviewQueueBackpressureTest,ReviewQueueCacheTest,RedisReviewQueueCacheIntegrationTest,MerchantWorkspaceApiTest,ReviewQueueApiTest' '-Dsurefire.failIfNoSpecifiedTests=false'
```

最后30项通过/0失败/0跳过（48.610秒），包含当前工作台HTTP实库5项、真实Redis5项、旧队列HTTP11项、旧缓存2项、回源保护2项、新workspace5项。原始日志仅忽略tmp/backend-b1-*.log。格式命令曾误用glob导致regex错误、再用管道正则被Windows cmd解释，最终使用逗号分隔的无管道正则成功，只格式化本步3文件。git diff --check 通过。

未运行：正式页面压测/延迟收益、新功能页面。另发现正式本机复用的 reviewer_demo 启动固定禁用缓存，独立 Compose 尚无 Redis；后续 B1.3 需要增加本项目 Redis 与启动接线，当前不能称日常启动已启用。商品批量查询 B1.2、评价 B2、付款恢复 B3 均未完成。旧实验报告不重算或修改hash。
