# 完整RAG批次冻结

manifest.json在新32真实Agent运行前生成。生产源码固定工程提交4c1b67e，34文件hash、入口/原案例/Gold与预算/模型参数冻结；历史真实before的开工生产hash核验见reports/rag-delivery/baseline-provenance.json。真实run与匿名源审的完整结果/失败见reports/rag-delivery/README.md。

公开政策源审为模型辅助标签，正式人审准确率null；外部原文/短引用可信账本/完整语义请求缓存忽略，不自动发布到商家。当前eval默认strict改为rag-delivery-v13是在真实run/匿名评分完成后；只改回放入口，不变生产RAG/Agent循环，final-entry-audit.json保留入口差异。控制对照使用保存的精确报告，不重跑before或以更换预算冒充收益。

依赖锁保持。临时PG只证明SQL/SDK逻辑，原Docker部署、Java整链与独立人工确认没有执行；模型评分包含协议失败与来源误报，不能称全面质量达标。
