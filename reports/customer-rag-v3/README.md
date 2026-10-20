# 客服RAG第三批：候选并集与Cross-Encoder（2026-10-20）

用户批准固定Query比较当前RRF、候选并集精排与商城全规则精排；随后明确本机有GPU，要求使用GPU推理。生产策略/依赖锁/旧报告/Gold保持，本批先离线比较再按证据决定接入。

## 冻结与实现

- 原Query保持不变，各路候选最多5；A为当前三路RRF，B0为RRF先截前5再Cross-Encoder，B为三路候选完整并集去重后Cross-Encoder，C为当前商城全部同店/版本规则直接Cross-Encoder。B0用于检查过早截断，不是额外召回路径。
- 模型复用本机已有`BAAI/bge-reranker-base`，固定revision `2cfc18c9415c912f9d8155881c133215df768a70`，6个权重/tokenizer/config文件SHA在manifest；不下载新模型、不新增聊天API调用。
- 外部原始29问题与原18改写探针分别报告，复用66子块/缓存Query向量/已有CODEX_REVIEW依据集合。外部正式accuracy仍不声明盲测。商城3保存模型Query+6合成探针分别报告，6规则/店；不虚构新事实或改原Query。
- 必要依据在候选并集是否齐全、最终Top3/5完整覆盖、逐例退化和增量耗时分别保存；无答案/需澄清不计完整回答分母，PARTIAL逐例保留。评分标签不进入召回/模型输入。
- 精排输入为原正文，max_pair_tokens=512，逐对检查、超限拒绝、不静默截断；batch8，不用评分阈值过滤条件。每个case/候选策略执行两次独立forward，核对排名一致；三次预热另列，不当正式延迟。计时仅含候选去重、分词、模型推理/排序，不含前置召回/Query编码/模型加载，不是端到端SLA。

## GPU环境

实测`nvidia-smi`：NVIDIA GeForce RTX 5060 Laptop GPU，8151MiB，driver592.01。原`agent/.venv`为PyTorch2.14.0+cpu，CUDA不可用。遵用户要求，从PyTorch官方cu130索引安装**同版本**2.14.0+cu130到忽略目录`tmp/customer-rag-v3/cuda-site`，只供本实验通过临时PYTHONPATH优先加载；不覆盖原CPU安装、不改uv.lock/项目依赖。不安装驱动或系统CUDA工具链。

最初[CPU准备manifest](../../evals/customer-rag-v3/manifest.json)已在用户指定GPU前冻结，**未运行**；保留原文件，不篡改其hash。实际使用另存[GPU manifest](../../evals/customer-rag-v3/manifest-gpu.json)，绑定本次代码/hash、cuda:0、FP32、TF32关闭和CUDA同步计时。没有CPU结果与GPU结果混算。环境探测/真实加载及测量状态将在实际执行后追加。

准备命令：

```powershell
uv pip install --python agent/.venv/Scripts/python.exe --target tmp/customer-rag-v3/cuda-site --no-deps --index-url https://download.pytorch.org/whl/cu130 'torch==2.14.0+cu130'
agent/.venv/Scripts/python.exe scripts/customer_rag_rerank.py --freeze --manifest evals/customer-rag-v3/manifest-gpu.json --device cuda:0
```

官方来源：[CUDA安装选择](https://pytorch.org/get-started/locally/)、[固定版本CUDA wheel索引](https://download.pytorch.org/whl/cu130/torch/)、[CUDA同步计时说明](https://docs.pytorch.org/docs/stable/notes/cuda.html)。无需据模型在旧实验的CPU延迟推断本机GPU性能。

验证准备：新实验测试先因缺模块收集失败，实施后3通过；加入GPU同步时序测试后4项，加原融合6项共10通过。覆盖候选尾部保留/去重/跨范围及原文冲突、完整pair输入/分数非有限/数量错误/长输入拒绝、同步在计时前和forward后调用。两实验脚本/帮助模块Ruff通过（初次行宽已格式化），正式真实推理尚未开始。原四历史脏文件及旧资产不夹带。
