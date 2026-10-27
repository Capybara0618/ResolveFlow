# 仓库说明

| 路径 | 内容 |
| --- | --- |
| java | 核心Java服务、共享契约与Fulfillment兼容模块/测试 |
| agent | AgentScope、Harness、检索/恢复、核心测试和小夹具 |
| web | Vue3界面/测试/锁 |
| contracts | 核心/兼容Schema、OpenAPI、跨语言夹具 |
| fixtures | 初始化合成商品/账号/政策 |
| infra | Compose、数据库初始化、MQ配置、版本锁 |
| scripts | 启动/初始化/契约/验证及必要小型评测依赖 |
| evals | 公开入口数据和恢复测试包 |
| docs | 运行/系统设计/开发/精选结果与契约引用规范 |

计划、进度、交接、原始报告、试验spike和一次性脚本保留本地，当前Git版本解除跟踪。小型旧坏例在agent/tests/fixtures/regressions，公开回归不读取本地reports。

core等兼容规范被Schema/测试按字段和行号引用，仍保留。操作先读[本机运行](local-runtime.md)、[系统设计](system-design.md)、[开发验证](development.md)，旧任务文字不作为当前开发指令。

只整理当前文件树，不重写历史；完整clone仍下载旧对象。浏览当前版本是精简目录，只需当前源码可用浅克隆。gitignore防止本地资料未来重新入库，不能抹去历史提交。

本次整理前文件树4763项、约413MB，整理后约1117项、13MB（按Git跟踪内容计，不含历史对象、依赖和构建产物）。3675项资料解除跟踪，工作副本仍留本地；整理前的逐文件校验备份保存在仓库外。构建及关键启动检查结果与尚存失败见开发验证。
