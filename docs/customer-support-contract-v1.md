# 客服会话与人工核查契约 v1

2026-10-20。承接[首场景](customer-agent-scenario-v1.md)和[双端预期图](ui-customer-agent-v1/README.md)。本批先实施真实的会话记录与人工接续，Agent咨询运行和退款摘要确认在后续纵向小步接入，不用固定话术伪装自动客服。当前进度只看[todo顶部](../tasks/todo.md)。

## 对象与归属

Case服务拥有conversation、message和support_ticket；Commerce仍拥有交易/物流，Python仍拥有Agent run。第一版入口限平台买家和MERCHANT_ADMIN，沿用一个商家账号管理一家店。后端根据本人订单行确定merchant/customer/order归属；请求不接受merchant、buyer、customer或金额覆盖。

- 同一buyer与line只有一个持久conversation，换商品恢复其独立历史。创建先在事务外查询Commerce，短事务内锁当前账号、店铺/绑定，再保存商品展示快照。快照不作为实时物流或退款金额的授权依据。
- message追加不覆盖，包含作者、接收方、序号和可选ticket_id。ASSISTANT接收方的客户消息为私有咨询记录，本批仅保存，尚不触发模型；MERCHANT消息必须关联已确认的咨询核查单。商家回复有明确作者。
- support_ticket保存客户确认的摘要与所选客户原文快照；不预留资金、不生成Case/退款授权或调查run。商家只读取本店ticket、共享快照和该ticket下的公开消息，不能读取全部conversation。
- conversation.version对所有新增消息、转交和状态变化递增，写入必须匹配expected_version；客户新消息可使旧预览/回复失效，前端需刷新后重看。该版本与Case revision/run fence独立。
- 未来Agent turn绑定conversation/input_version/run_id，发布前比较版本；旧输入回复不作为新输入答案。本批不增加伪case_id、内部工具权限或第二套Agent循环。

## 路由与状态

所有写操作携带Idempotency-Key（1–128位字母数字下划线横线）。短事务按账号→商家/绑定→会话顺序加锁；会话内幂等回执绑定actor、operation、key和完整请求，重复相同请求不追加消息，不同载荷409。响应丢失重试返回原写结果，即便当前version已前进；再GET可取最新状态。

| 路由（前缀/api/v1/support） | 行为 |
| --- | --- |
| POST /conversations | `{line_id}`，打开/恢复本人订单行会话，不触发模型/退款 |
| GET /conversations | 本人会话倒序分页，limit默认20、最多50，before为上一页next_before |
| GET /conversations/{id} | 本人详情、最新核查单、最近50条消息；before_sequence可读取更早消息 |
| POST /conversations/{id}/messages | `{expected_version,text,recipient}`；ASSISTANT私有记录，MERCHANT补充进当前核查单 |
| POST /conversations/{id}/tickets | `{expected_version,summary,shared_message_ids}`；确认转交，最多20条本会话客户原文，不接收前端伪造的原文内容 |
| POST /conversations/{id}/resolve | `{expected_version}`，客户确认解决；必须先有商家回复 |
| GET /tickets | 本店核查单倒序分页（相同limit/before规则） |
| GET /tickets/{id} | 本店核查详情与最近50条公开消息；before_sequence翻更早消息 |
| POST /tickets/{id}/messages | `{expected_version,text,kind}`；REPLY回复，REQUEST_INFO请求补充 |

打开会话以buyer/line唯一性幂等，不要求Idempotency-Key；其余POST遵循上述回执。新单PENDING；商家REPLY→REPLIED，REQUEST_INFO→WAITING_CUSTOMER；客户MERCHANT补充→PENDING。客户在REPLIED状态可确认RESOLVED；解决后再次补充可重开同单。同会话已有核查单时再次转交409 TICKET_ALREADY_EXISTS，应接续原单，不重复创建。第一版不增加独立“领取/处理中”操作，不设自动关闭或两轮咨询上限。

普通咨询不自动转交。转交后客户仍可显式切到ASSISTANT保存私有记录，不自动共享；新增摘要不静默覆盖已确认快照。申请退款仍走现有客户Case入口，待后续实现可追溯的确认摘要与咨询关联，商家回复不能代客户申请。

## 列表、错误与验证

列表以不可变sort_id倒序，查询先限定buyer/merchant；跨主体游标只影响本人的页边界，不取得别人的数据。消息按会话序号，每页最近50条，next_before_sequence继续更早页。返回集合均有上限，不截断冒充完整历史。

401登录失效；403角色不支持；404资源不可见；400无效参数/未知字段；409版本不符、不同载荷重用key、重复转交或非法状态。文本1–4000字符，摘要1–2000，版本正整数。商家读模型私有上下文、退款审批和实时物流不在这些接口权限内。

首批验证：真实隔离MySQL迁移+HTTP会话/消息/转交/回复/补充/解决；幂等重试/不同载荷/旧版本；跨买家/商家与平台管理员；共享原文范围；会话隔离/分页；Case/授权/退款槽不增加。Commerce使用有主体检查的stub时明确标记，不当作真实跨进程验收。随后连接正式网页并集中验证界面，原冻结实验与简历不改。
