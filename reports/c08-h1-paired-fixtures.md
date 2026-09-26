# C08/H1 六组配对合成输入与Gold隔离（2026-09-26）

按 `docs/agent-harness.md` H1 与 `docs/evaluation.md`，建立 `evals/datasets/h1-pairs-input.json` 的6组/12例同诉求、同主体、不同权威事实案例；全部归入预定test分层。`h1-pairs-gold.json` 分文件定义允许/禁止终局动作、必须观察和引用；当前标记 `draft-not-human-reviewed`，本提交固定文件版本，但**尚无人类审查**。`h1_pairs.py` 校验家族完整、作用域一致、证据确实分歧、A可建议退款/B禁止退款、Gold不混入输入，并支持输出单例seed。此seed含权威事实，仅供未来隔离执行器灌入真实工具后端，**不得直接作为模型消息**。另加 `h1-run-record.schema.json` 规定将来live运行的请求hash、轨迹、来源、验证和失败记录最小字段。同步修正数据集README的旧240案例口径。

验证（工作目录 `agent/`，2026-09-26）：`./.venv/Scripts/python.exe -m pytest tests/unit/test_h1_pairs_dataset.py -q -p no:cacheprovider --tb=short` → **3 passed**；`./.venv/Scripts/ruff.exe check ../evals/datasets/h1_pairs.py tests/unit/test_h1_pairs_dataset.py` → **All checks passed**；`./.venv/Scripts/python.exe ../evals/datasets/h1_pairs.py` → **6 pairs / 12 cases，Gold isolated，live runs=0**；`--export-case H1-01-A` 正常导出且不含Gold；`git diff --check` 通过。首次Ruff发现一处行超长，已修复后重跑通过。

限制：当前仅有离线结构验证；没有Case/Commerce/政策服务seed和执行runner，没有live模型、人工Gold审查或H1分数。未运行本步全量Python、Java、all-offline、live及H1–H5。下一动作是设计独立的评测seed/捕获入口并确保只把诉求送给Agent，或在费用配置明确后先补最小真实服务试跑；不能用fixture验证代替H1。C09预算冲突须先按总12次规范界定，不能照搬spike的12+2。
