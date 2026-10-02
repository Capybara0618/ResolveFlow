# 客户完整申请实施与验证

2026-10-02，新第二批。复用此前未提交客户接口原型、持久身份、原订单/材料/撤销及工作人员业务，不重做身份迁移或Agent循环。页面对应v2的02–06/17；当前详细进度仅在tasks/todo.md顶部维护。

## 客户接口收口

- 新增本人分页列表、客户最小详情、订单行资格和带If-Match的当前问题回答，共4个客户路由；新增V20两项索引，旧迁移及数据保留。服务器按JWT的merchant/customer过滤，工作人员访问403，其他客户/商家详情404。客户投影没有方案、授权、模型/工具原文或工作人员actor。
- 问题截止为事件发生后72小时与持久工单期限的较早者，新旧材料入口均拒绝过期回答；问题ID/工单版本自动由客户端关联。回答仍走原材料事务，增加修订并产生新调查绑定。
- 修复创建幂等重放泄露：先核对原工单归属，再比较请求体，竞争重放路径同样受保护。已消费且返回审核/等待状态的申请依然只读；明确执行失败采用原operation匹配的非陈旧持久事件给出公开说明。
- 核心路由表及OpenAPI同步新增4条（Case22→26）。修复原型分段生成的YAML锚点重名，保留旧模式和所有断言；客户响应/请求例子进入既有契约校验，并测试客户投影拒绝内部成员及回答版本格式。

实际验证：Java21，Maven `-pl case-service -am -Dtest=CaseApiTest,CustomerWorkspaceApiTest,EvidenceApiTest,CaseCancelApiTest,ManualProposalApiTest,ReviewerActionsApiTest -Dsurefire.failIfNoSpecifiedTests=false test`，实际运行前5个存在的类共50 passed（9/7/8/8/18），最后指定名不存在、没有运行，不将其计为通过。Python `-m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py -q`：121 passed。定点Spotless apply覆盖8个本批Java文件，实际清洁8文件；不格式化Commerce他人改动。

失败和修复：权限失败回归先6项中1 failed（另一客户实际拿到201），修复后上述50通过；契约原型先38 failed/33 passed（锚点重名及路由数），修复后71通过，再加入投影检查首次因错用ValidatorBundle.iter_errors得到1 failed/120 passed，改用既有accepts/error_messages后121通过。消费测试首次fixture直接插CONSUMED违反审批CHECK，修为先建待审、记录批准再标消费后通过，不把无效fixture当有效RED。初始Maven未引用带点参数、Spotless误用glob和经cmd解释的管道正则导致命令失败，后改为引用参数及逗号分隔无管道正则；无效命令不计通过。临时日志在忽略的tmp目录，未提交原始敏感运行日志。

上述为接口收口时点；下面记录本批接续的正式页面与集中验收。没有调用收费模型、批准演示历史申请、清库或删卷。

## 正式客户页面

CustomerWorkspace接入真实登录，替换旧客户表单；对应v2的02–06/17：本人订单、固定全额申请、本人申请筛选/分页、原始申请/材料、两轮问题及回答、撤销和公开结果。客户只读专用投影；无需手填问题或工单内部编号。复用共用页头/弹窗/图标与已有Java写事务；商品图片缺失使用明确占位，无媒体假上传或虚构客户资料。

创建结果未知保留同一幂等键及请求体；申请成功而材料失败仅重试材料；普通材料丢响应先读取核对，未确认则冻结重复提交，后续刷新发现已保存即解除并清草稿。覆盖401会话失效、409旧版本保留草稿并刷新、过期问题禁答、消费/UNKNOWN只读、导航后迟到响应丢弃。草稿不持久存储，重新登录可继续查看服务器记录。详情用可见时15秒客户投影轮询；列表文本查询仅限已加载记录并明确说明。

浏览器发现第二轮人工补证后，结果卡仍可能显示第一轮审批理由：CustomerCaseService改为显示最新问题，普通重新调查不沿用旧决定。新增回归首次fixture用了重复timeline sequence而报错，修为顺序1/2后通过；这次无效fixture不记有效RED。补充运行实际存在的CustomerWorkspaceApiTest、ReviewDecisionApiTest、ReviewedEvidenceApiTest共28 passed（8/11/9），补齐前次误写不存在类造成的未运行范围。定点Spotless两文件apply通过。

## 实际双端闭环

在保留原数据的隔离demo中，从网页创建3条新合成申请，全部业务写入走网页/API。驱动只新增其自有3条订单，未SQL改工单、审批或退款状态。结果保存在[合成验收记录](customer-workspace/acceptance.json)：

| 订单行 / 工单 | 浏览器实际路径 | 最终结果 |
| --- | --- | --- |
| 91002015680 / a0e7cbdd-b0e7-4b5b-a5cb-61327f02709a | 建单＋初始材料→真实SDK mock建议→两轮人工问题/客户回答→调查预算失败→选材料/政策提交当前人工方案→批准授权→MQ/模拟provider执行 | CLOSED_SUCCESS，32900分，原始申请/两轮回答保留，允许动作空 |
| 91002015681 / f28bb098-63f9-48eb-8382-17da3caf83f2 | 建单→mock建议→第一轮问答/新建议→第二轮问答/新建议→专员最终拒绝 | CLOSED_REJECTED，公开人工理由，两轮ANSWERED，允许动作空 |
| 91002015682 / 8b11901d-c05c-4178-a2e0-03f7a06dffd7 | 从本人订单申请→本人填写原因确认撤销 | CANCELLED，不显示退款金额，允许动作空 |

第二条的revision1/2/3均经正式AgentScope factory、真实MCP物流、PG dense政策索引、lease/fence、持久模型/工具记录及回调outbox生成有效建议；mock脚本明确预写已知丢失规则，并使用真实检索得到的该条原文作窄查询，不作为自主推理/召回质量证据。人工可以拒绝退款建议，模型不审批。第一条覆盖多份材料使调查失败后的人工兜底，不把最后的人工方案写成Agent成功结果。

已有历史QUEUED run不能被验收worker消费，因此RunLease增加可选run_id定点领取，默认队列顺序不变，指定不存在/被占用时不落到其他run。新test先TypeError失败后通过；PG隔离schema的lease/recoverable worker/SDK恢复共26 passed。驱动禁止处理manifest以外工单、不重置失败run预算/manifest/deadline；失败后通过真实追加材料产生新修订。原62条调查的status/version/fence前后完全一致；默认只读Agent保持关闭新调查，收费模型调用0。

`verify-ownership`实测同商家另一客户与另一商家客户分别读取3条新申请和对应资格，共12个404；`verify-outcomes`核对终态、金额、动作及两轮回答；`verify-isolation`核对62条旧run。首次隔离脚本断言失败且未保留HTTP状态，不归因为已确认业务缺陷；保留数据重启新版后12项通过，驱动现在失败会输出账号/路径/状态，不输出token。

## 上下文限制与修复证据

固定8K输入上限下，带两轮问答、多份材料及政策约束的P0/P1/P2会溢出；失败码CONTEXT_REQUIRED_OVERFLOW真实保存。未抹掉失败，也没有通过调大预算/删例外使测试通过。验收驱动最初错误使用8192 provider容量，后来对齐既有演示32768；独立Harness步上限仍8192。top_k=1早期窄查询命中另一条政策而固定mock脚本耗尽，原run随后随追加材料被取消，未改同run脚本重跑；最后改成先验证真实索引能命中已知规则再定点领取。

P1现在对连续同字段材料使用无损字段表，保留内容、来源/版本/hash、记录顺序、缺失与null差别、问题关联及未知字段；结构化run快照不变，只有发送文本格式变化。有效RED先证明旧输出没有字段表，修复后decode回原文完全一致；新增巨量材料仍拒绝的保护回归。上下文/引用存活/情景/裁剪四类42 passed。无写入的诊断重建：第8版样例原需8209 token而拒绝，压缩后同样的3次mock决策完成；第9版累积7份材料仍需8280 token而拒绝，正式链路该版仍失败。这是保留的限制，不称“多材料Agent全面优化完成”；当前可由人工方案继续，后续Agent优化应处理预算内的信息组织，不能直接删除事实。

## 集中验证与桌面证据

- `pnpm --dir web test`：最终13文件83 passed；`pnpm --dir web build`：vue-tsc及40模块构建通过。早期旧客户断言/表单提交方式造成失败，更新为实际表单路径后通过，未删除业务断言。
- Python核心协议121 passed（API提交时）、上下文42 passed、恢复/lease26 passed；定点`python -m ruff check`通过5个Python文件。首次Ruff发现未用import和两条超长测试行，修复后通过。
- Java本批先50 passed，后补充3类28 passed；CustomerWorkspace重复运行，不把执行次数相加称独立用例总数。前述格式检查通过。`git diff --check`通过；`python tmp/check-customer-links.py`核对62个本地文档链接及合成结果/12项权限记录，无token/key字段。
- `.\demo.ps1 stop`、`.\demo.ps1 -NoBrowser`保留数据冷启动完成，新版3 JAR、政策导入0/skip6、index READY、只读Agent/桌面页面就绪。一次尝试运行中重打JAR被Windows文件锁拒绝，停对应demo后由既有入口构建重启成功。启动驱动仅为其自有历史2条演示订单补齐商品展示字段，未改历史工单/金额/退款；旧run隔离核对再次通过。
- 正式浏览器验收用Computer Use控制实际Vite页面，完成新申请、两轮回答、当前审批、拒绝、撤销和重登录查看；修正customer-main盒模型溢出及旧order-row flex覆盖。1440实际client宽1425、1280宽1265、1680宽1665（滚动条15px），scrollWidth一致，无横向溢出；1280详情刷新按钮在视口内。最初全局viewport作用于临时工作人员tab，未据其无效尺寸宣称通过；关闭该tab后实测客户tab并重存截图，最终清除viewport覆盖。

实际截图：[1440结果](customer-workspace/customer-result-1440.png)、[1280结果](customer-workspace/customer-result-1280.png)、[1680申请列表](customer-workspace/customer-list-1680.png)。只记录桌面网页，不安排移动产品。登录使用demo-customer / demo-pass-1001；专员demo-reviewer / demo-pass-1003；当前入口http://127.0.0.1:5174，默认只读Agent，不消费新的收费调查。

未运行：本批live调用、旧全仓golden/费用评测、移动端专项、下一批多人领取/转交/人员管理。第三批及第四批管理员概览/只读政策、角色导航等尚待实施；本批完成客户业务接线和对应桌面布局，不宣称全部19项设计或全系统已完成。
