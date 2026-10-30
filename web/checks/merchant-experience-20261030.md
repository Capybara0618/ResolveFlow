# 商家体验优化验收（2026-10-30）

## 一、聊天身份

商家咨询标题原用工单摘要与助手头像，消息头像下重复姓名。现在列表/聊天抬头使用买家昵称与头像，商品/规格/订单尾号为辅助定位；问题摘要仍显示在转交卡片。双方消息只留头像，title/aria-label保留可识别姓名。

TicketDetail新增buyer公开资料（昵称、avatar_id），限已归属本店的已转交核查单。列表批量查询资料避免逐行身份请求；头像读取沿用readTicket权限边界，新路由不开放私人聊天或未转交会话。原逐消息身份路由及消息可见性不变，买家不读取商家投影字段。

- 新回归先红：前端标题是摘要；后端buyer字段缺失。第一次后端回归测试误用/handoff及重复/api前缀404，修正测试路由后得到字段缺失的预期失败。
- JDK21 Maven `-pl case-service -am -Dtest=SupportApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：36项通过，含无共享消息仍显示买家、跨商家不可读/买家不可读商家头像入口、原私聊共享隔离。
- `pnpm --dir web test -- tests/support-workspace.spec.ts tests/support-events.spec.ts`：41项通过；`pnpm --dir web build`通过。
- `uv run --project agent --frozen pytest agent/tests/unit/test_contracts_support.py agent/tests/unit/test_contracts_openapi.py -q`：105项通过。新增路由/闭合buyer结构与fixture同步；后续将新增路由错误response引用改为现有ApiError内联，未改业务协议。
- 受归属脚本重建/重启Case，商家admin01实机进入原核查单：标题“购物验收买家·已保存”，买家照片加载完成，左右列表/抬头一致，消息姓名标签0，无横向溢出。截图tmp/merchant-experience-20261030/chat-identities.png。
- 仅登录/读取，无新消息/订单/审批/模型调用。Agent仍关闭，原4无关脏文件保留。

其余记录分页、概览、政策页在本批后续步骤记录；本节不代表其已完成。
