# 第三批：本商家人员管理

2026-10-02，按已批准多人协作方案及v2人员页实施。账号维护复用持久身份，不改变工单负责人、输入修订、金额或Agent权限。

## 后端子步

- 新增人员列表/真实筛选计数/绑定游标、新增工作人员、姓名/角色/启停维护、密码重置及账号审计，共5条Case核心路由，29→34。V23只追加账号维护版本和审计表；username及merchant/customer固定。
- 写事务按商家→有序账号锁序；锁内当前读校验签名身份与目标维护版，商家锁保证最后启用管理员检查与变更原子。PBKDF2随机盐计算在短事务前，凭据不回读、不进入审计。姓名变化不杀会话；角色/启停/密码增身份版，重新启用不复活旧token。
- `StaffAdminApiTest`先7项红灯（正式路由尚不存在，404），实现后7项通过，再补并发/等待锁签名撤销/读取快照过期及禁用保留负责人，共10项通过。两个管理员并发停用仅一个成功；旧版本写入不覆盖已提交状态；新工作人员真实登录并领取工单，禁用后负责人/工单版本/输入修订保留。
- 实际命令：Java21下`java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am -Dtest=StaffAdminApiTest -Dsurefire.failIfNoSpecifiedTests=false test`；最终`... -pl case-service -am test`。shared-kernel 62 passed；case-service 314 passed、4 skipped、0失败/错误。4项既有跳过未宣称通过。
- Spotless对新Service/Controller/测试及ApiExceptionHandler精确正则运行apply成功。核心契约同步，新增fixture验证凭据泄漏/跨主体字段/非法新增角色及原账号版本。第一轮合同生成锚点与旧YAML重名，修复为独立名称；随后2项新测试误用ValidatorBundle方法，修正后`pytest agent/tests/unit/test_contracts_core_routes.py -q`为78 passed。一次误指定不存在测试文件导致零步骤失败，已纠正，未记通过。

前端与浏览器验收接续本功能批次。后端测试使用Testcontainers独立MySQL及合成人员，不改变演示账号或生产数据；未调用模型、收费评测或执行新退款。临时日志在忽略的tmp目录，不含交付依赖。
