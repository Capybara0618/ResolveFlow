# 当前评测体系 v1

三商家、两历史版本（六bundle），60个检索查询、32个Agent案例（16对）、20项Harness与8项上下文检查。全部为合成资料，标注由Codex按政策核对，未经用户或独立专家人工审查。

输入与答案分离，`manifest.json`记录文件hash。配对及查询意图家族不跨dev/test；Agent主场景dev为未发货/丢失，test为签收争议/质量核验，不能宣称同分布随机测试。政策正文包含条件和例外，金额/权限由程序控制。

维护者通过`build_assets.py`创建数据版本；评测时只读取和校验，不能重新生成Gold。正常运行入口见[开发验证](../../docs/development.md)与实际报告（原始说明留本地）。`replay/golden`另存五个当前SDK合成持久轨迹，包自身files.json校验内容完整性；不是商城日常数据初始化入口。

当前公开入口与边界见[开发验证](../../docs/development.md)和[精选结果](../../docs/evaluation-results.md)。
