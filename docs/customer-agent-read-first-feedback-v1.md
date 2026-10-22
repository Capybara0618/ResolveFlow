# 无任务分项回答的完整反馈

2026-10-22，实际只读解耦确认中，R01已经查到物流，但第一次ANSWER_PARTS无初始tasks，被render_answer归为覆盖错误；该反馈仅提示先声明tasks，模型下一次补tasks后仍漏当前原文dialogue_events而失败。

本小步仅将“没有初始任务”独立归为TASKS_REQUIRED，复用已存在的发布反馈，明确required_on_answer为tasks和dialogue_events，要求同层声明当前原文后给parts。程序不自动新增任务或事件、不放宽来源，不增加一次纠错机会；已有任务缺覆盖仍是原覆盖错误。

两项离线验证使用刚保存的真实响应：关键测试先1失败/1通过；补完整事件的脚本修正可一次通过，原保存的“仅补tasks、不补事件”仍拒绝且原始轨迹字节不改。脚本修正只证明反馈与机制接线，不证明真实模型会遵循；此小步不运行额外付费模型。

这发生在真实确认冻结版本之后，原98文件清单应按预期拒绝当前tasks.py hash，不改旧hash或覆盖原结果。最近真实质量仍见[报告](../reports/customer-agent-read-first-v1/README.md)，最终回归/收口仅tasks/todo.md顶部，业务入口来源选择仍为未修问题。
