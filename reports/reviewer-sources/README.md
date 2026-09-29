# 审核调查原始记录交付

2026-09-29。当前修订的只读投影已贯通Agent持久agent_tool_call→Case权限/绑定校验→审核页面。保留来源、版本、hash和读取时间，分项全匹配才关联正文。区分无绑定、不可用、无记录、超长省略；明确mock。不调用模型、重读工具或修改历史。

物流结论、状态和更新时间可直接读，完整结果折叠；无方案也能看调查。成功状态改绿色，已处理方案不再写“待审退款额”。

## 验证

- 新接口先因404失败，完成后test_reviewer_sources.py 4 passed：scope/商户/客户/case/revision隔离，无写入，32KiB及40条上限，fixture双侧协议。
- 投影初版+test_run_api.py共21 passed；之后新增2项单独补跑通过。test_contracts_openapi.py 87 passed，Ruff通过。Starlette既有弃用警告，无跳过。
- Java ReviewerInvestigationServiceTest、ManualProposalApiTest：21 passed / 0 failed / 0 skipped；spotless和package通过。覆盖角色/商户、错绑定、白名单和不可用。
- 前端9文件34 passed，build通过；覆盖错hash、切换工单迟到响应、mock和故障提示。
- Docker核心七容器启动，Gateway健康/认证/隔离smoke通过。新接口经Gateway读取既有待审和已结束记录。
- 实际合成样本acc36759-2b64-4541-9ad5-13379a9cc71d返回COMPLETED/mock/2条记录；浏览器展开见物流LOST及version/hash/时间，模拟退款25.99 CNY，工单只读。未发起新审批或退款。
- 人工样本d3cd4ec2-ed0d-4ab8-b0b5-2499b3419540当前修订无绑定，准确返回NOT_SCHEDULED。部分旧run没有保存工具正文，未补造。

## 问题及边界

跨日恢复时容器已停。上次打包中断后增量repackage报Unable to find main class，仅clean构建产物后恢复。两次Compose启动重叠曾导致临时容器名称冲突，等待首次完成后顺序重试恢复，无删卷清库。最新Case/Agent已重建启动。

未调用收费模型、未跑新工单完整退款、未全面验收窄屏。历史修订选择器未实现，工具结果仍有JSON展开，不能据此宣称真实模型质量提升。

桌面1670×1000检查截图：[desktop.png](desktop.png)。
