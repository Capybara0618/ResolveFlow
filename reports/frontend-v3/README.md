# V3 审核工作台交付记录

2026-09-28。按用户要求集中验收，不逐个样式小步重复运行测试。

## 交付

- 正式 `web/src/App.vue` 接入参考图四区比例、独立队列卡片、紧凑订单/文本材料、浅蓝建议与时间线、底部审批操作。登录页与客户入口沿用同一视觉基础。
- 样式独立到 `web/src/ui/workbench.css`；正式页和开发预览共享 tokens、ReviewIcon、ReviewDialog。弹窗包含焦点循环、Escape、焦点恢复、请求中禁止关闭。
- 三种审核决定先打开理由弹窗，理由必填；提交冻结打开弹窗时的 case/authorization 版本，SSE 更新不能静默替换已审版本；409 后关闭旧决定并刷新。
- 完整证据、来源、方案及全部事件仍可展开。人工方案保持 HUMAN 标识；无授权/已消费授权不能重审。未增加支付、客户画像、媒体上传或自动真实性识别能力。
- 补全已有开发预览的缺失样式/素材，使用本地 SVG 插画，不依赖远程图片。`?preview=review` 仅开发环境开放，生产构建不包含预览页面。

## 实际验证

- `pnpm --dir web test`：6 个文件，26 passed。覆盖客户创建、服务端拒绝、真实字段、三种审核决定的冻结版本、409、只读预览交互、键盘焦点与请求中关闭限制。
- 先改审批交互测试：原页 2 failed / 6 passed（缺确认弹窗），实现后通过。首次集中测试 8 failed 是未挂载文档的组件测试仍以 click 触发表单默认提交；改为触发 form submit，保留所有原业务断言。构建和差异检查通过；曾出现 Python Windows CRLF 导致 diff whitespace 报错，已统一 LF。
- `pnpm --dir web build`：vue-tsc 与 Vite 成功；无新增依赖或锁文件变化。`git diff --check` 通过。
- 最初 Docker Desktop Inference manager 初始化失败，正式组件先用 `web/tmp/review-fixture.*` 合成接口检查（忽略目录、不提交）。用户恢复 Docker 后，运行 `docker compose -f infra/compose.yaml --profile core start mysql postgres redis agent commerce-service case-service gateway`；7 个容器 healthy。
- 真实浏览器正常入口：demo-reviewer 读取 5 条队列，打开既有合成工单 `d3cd4ec2-ed0d-4ab8-b0b5-2499b3419540`，32900 分、2 项材料、人工方案、PENDING_REVIEW 授权均来自后端。打开批准弹窗，确认空理由不能提交，Escape/取消后授权仍为待审。未提交真实审批。
- 1670×940 正式页：建议区 bottom≈816，审核操作 top≈832，标准样本建议与操作均在首屏；1280×900 和 390×844 无文档横向溢出，手机队列可在自身区域横向滚动。移动审核弹窗宽350px且可取消。
- demo-customer 正常入口读取20条订单行，390px无文档横向溢出。浏览器控制台未发现 error/warn。
- 开发预览：切换工单同步客户/商品/建议；待补证项不可批准；材料详情可打开并 Escape 关闭；本地模拟批准明确提示未提交真实工单。1280/390px无文档横向溢出。

## 截图

- [正式审核页：真实服务读取、本地合成业务样本](review-desktop.png)
- [真实客户订单入口](customer-desktop.png)
- [登录页](login-desktop.png)
- [独立设计预览：合成字段](design-preview.png)

## 边界

本轮未运行退款写入端到端、付费模型、Java全量测试或C12评测；既有C12脏文件与数据库保留。当前订单API仍无商品照片、客户画像与完整支付流水，正式页显示现有可信数据，不将预览示例伪装为业务结果。核心服务和本地Vite保留运行供用户查看。
