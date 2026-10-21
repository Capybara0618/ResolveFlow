# 客服指南业务接入与启动预热

2026-10-21。实施依据为[本批协议](../../docs/customer-rag-integration-v1.md)，架构见[采用决定](../../docs/customer-rag-architecture-v1.md)。本报告是已实现的工程与检索验证，不是新真实生成模型的回答质量或整套Java/Python/浏览器同时运行的验收。

## 实际交付

- 10篇已实现流程说明形成`support-guide-v1.json`，版本2026.10.21-v1，保留导入来源/hash、完整正文及逐篇审计记录。AgentScope按需调用无参数`get_support_guide`完整读取，计入本地读预算；无需政策索引或订单事实读取。退款政策继续使用原本店/版本/generation三路RRF；实时物流等继续走业务工具。
- 新来源类型KNOWLEDGE使用现有O编号，与POLICY/P分开；Java协议、fixture、校验、客户确认共享同步兼容，私有对话仍排除。买家和商家可展开“使用指南”原文和版本。逐篇审计hash不重复塞给模型，完整记录留在持久来源/最终引用；正文没有被摘要或截断。
- 新工具和资产源码hash进入run manifest；运行恢复遵守原预算/fence，已保存指南和模型结果可以复用，同run不静默换版本。Python实际ASGI接口→SupportRuntime→AgentScope→隔离PG持久结果已验证，同请求第二次返回相同结果，模型仅首次两次脚本调用。
- 政策索引开启时默认启动预热共享embedding和BM25分词器，日志WARMING→READY并显示耗时，失败阻止就绪并清理缓存。显式`RESOLVEFLOW_SUPPORT_PREWARM=0`关闭。预热不访问生成模型/数据库、不消费队列；未采用实验owner线程、CE默认或新依赖。

## 真实本地模型与保留PG测量

三次独立Python进程，原9条Query×3轮=每组27次实际`retrieve_policy`。真实FastAPI生命周期共享权重，BGE-small-zh-v1.5原revision/512维，CPU默认intra/inter-op均16；没有改成旧实验的4线程。PG连接强制只读，原商家manifest与generation不改。未发送生成模型请求、未启动业务worker。

| 模式 | 应用启动等待 | 首次政策检索 | 后26次P50 / P95 |
| --- | ---: | ---: | ---: |
| 关闭预热 | 74.5ms | 9578.9ms | 68.2 / 133.4ms |
| 初版仅embedding预热 | 30416.5ms | 830.4ms | 167.5 / 267.3ms |
| 最终embedding+分词预热 | 9410.1ms | 68.5ms | 67.7 / 104.4ms |

最终27次全部P50/P95为68.5/103.9ms，各次`dense_model_load_ms=0`。初版首查正文BM25排名阶段729.3ms，主要是jieba第一次初始化；因此补入分词预热。最终对应阶段12.6ms。预热将加载成本前置到启动，并未消除加载总成本；各进程启动/热态波动不能解释成稳定吞吐或固定倍数。上一批4线程35ms与此默认16线程口径分开。

原始[关闭预热](startup-lazy.json)、[初版预热](startup-prewarm.json)、[最终预热](startup-prewarm-v2.json)全部保留。前两份对应[无损保存的原测量脚本](startup_profile_v1.py)，最后一份对应当前`scripts/customer_rag_startup_profile.py`，各自runner hash核实；最终另存实际生产文件hash。

81次排名完全一致，原P02必要规则Top5漏召回仍保留；指南接入与预热没有声称修好该政策排序。三组public11表全行见证一致，临时测试schema验收后清理，卷保留。此处是政策检索耗时，不含生成回答、Java转交和浏览器渲染。

## 验证与发现

- Java：真实隔离Testcontainers MySQL/HTTP，SupportApiTest13+SupportWireTest2=15通过；覆盖KNOWLEDGE确认共享与私有对话排除。三个相关Java文件Spotless逐文件apply/check通过。
- 前端：guide/context/workspace/client四文件21测试通过（含新增2项先失败后通过），`pnpm build`的vue-tsc/Vite通过。未新做浏览器全栈体验测试。
- Python指南/来源/Query/检索/契约/API/隔离PG恢复：62通过；预热/HTTP运行控制/政策状态：31通过；新增实际指南ASGI/持久链路1通过。API测试重叠1项，合计93个不同相关测试通过，均无跳过。7个修改生产模块严格mypy通过，相关源码/测试及当前测量脚本Ruff通过。app中原两个裸dict返回注解补全后严格mypy通过。
- 扩大范围加入旧`test_deployment_factory.py`时是37通过/3失败，不能写全仓绿。在`3c61a96`原源码+contracts独立快照、同一锁环境重跑这3项，仍是2项脚本耗尽（2决策被要求3次、3决策被要求4次）和1项假传输请求数2而断言1。这是原有退款调查测试与当前循环不一致，未在本批删除断言或改调查逻辑。有效基线复跑3失败/0通过。
- 开发中指南工具先未注册而失败，接线后又触发CONTEXT_REQUIRED_OVERFLOW，定位到逐篇审计元数据，保留完整正文而压缩模型包后通过。预热先4失败/4通过，再8通过；分词预热接线断言先因缺少符号失败再通过。原Starlette BlockingPortal弃用警告保留。
- 验证命令曾误用Spotless glob、含竖线regex（CMD解释），改逐文件无竖线regex后成功；第一次基线只提取源码漏contracts，后一次误填不存在schemas导致归档失败，补齐contracts的有效复跑才用于结论。一次todo LF误变CRLF已在下一提交恢复。没有将失败/未执行记成通过。

## 可复现命令

项目根目录的PowerShell：

```powershell
agent/.venv/Scripts/python.exe scripts/customer_rag_startup_profile.py --prewarm 0 --output tmp/new-startup-lazy.json
agent/.venv/Scripts/python.exe scripts/customer_rag_startup_profile.py --prewarm 1 --output tmp/new-startup-prewarm.json
```

需要保留PG已启动在55433及既有本地权重；脚本输出文件必须不存在。使用同一最终脚本重测时两组均记录当前生产hash，前两份历史报告的语义按上表保留。

在agent目录设置`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_guide.py tests/unit/test_support_agent.py tests/unit/test_support_sources.py tests/unit/test_support_api.py tests/unit/test_support_query.py tests/unit/test_support_retrieval.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_support_embeddings.py tests/unit/test_support_api.py tests/integration/test_run_api.py tests/integration/test_policy_status_api.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_support_guide_api.py -q
```

前端在web目录执行`pnpm test -- tests/support-guide.spec.ts tests/support-context.spec.ts tests/support-workspace.spec.ts tests/support-client.spec.ts`及`pnpm build`。Java在java目录、JDK21执行`mvnw.cmd -pl case-service -am -Dtest=SupportApiTest,SupportWireTest -Dsurefire.failIfNoSpecifiedTests=false test -q`。

## 后续边界

本批接线/预热已实现，服务保持停止，由下次正常启动加载新代码。真实生成模型是否按问题选择指南/政策、是否准确回答新流程，以及端到端回答延迟尚未新增测量；后续应固定少量代表场景验证，不把脚本答案当实际LLM质量。P02政策召回和旧调查3项测试问题分别保留，旧数据/Gold/政策/依赖锁及原四历史脏文件不改。
