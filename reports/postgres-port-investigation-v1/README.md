# PostgreSQL 55433端口拒绝绑定复核

2026-10-25，用户质疑“Windows保留端口”为何之前未出现，要求核查是否配置或实施出错。本次只做诊断；[原始结构化证据](evidence.json)保留当前系统查询、独立socket探针及原容器身份/健康时间，不复制凭据或完整Docker私有日志。

## 确认的事实

1. `netsh interface ipv4 show excludedportrange protocol=tcp store=active`成功返回55385–55484，包含55433；IPv6同样包含。persistent查询成功但为空，说明当前看见的是active运行时状态，不据此指定创建者。
2. `Get-NetTCPConnection -LocalPort 55433`未发现监听进程。普通Python直接对127.0.0.1:55433执行bind/listen，无SO_EXCLUSIVEADDRUSE和启用该选项两种均返回WinError10013；同一进程/权限绑定65433两种均成功，探针随后关闭。限制独立于Agent、PostgreSQL和Docker转发；不是只凭Docker错误文字猜测。
3. 重试`docker start resolveflow-review-demo-postgres-1`仍在宿主绑定55433时报相同拒绝，原PG未进入启动。最后成功启动时间是2026-10-24 22:42:45 +08:00，停止于22:53:10；22:53:07健康检查仍accepting connections。不能把今日启动失败等同数据库存储损坏，也未进行今日数据库内部完整性验证。
4. 原容器仍为9月29日创建的2697eb86cf0b，原卷`resolveflow-review-demo_demo-postgres-data`和127.0.0.1:55433→5432映射保持。Compose文件与最后成功页面验收be15578逐字相同；之后a442486/15aaab2没有改数据库端口，启动器只添加日志配置参数。

## 为什么以前可以

已证实“昨天同一容器成功绑定、今天同端口被Windows拒绝”，支持宿主端口可用性在两次启动间发生变化；没有保存昨天的excludedportrange快照，因此不能断言保留段恰在何时新建。

宿主最近开机为10月23日09:21:20，不能简单归因为“这次重启电脑”；Docker本次日志显示WSL网络模式NAT，并有10:02/10:10端口添加后立即移除，未记录55385–55484的申请者。System日志有09:42:54 WSLService响应超时，但不证明它创建了该段；WinNat/Oper无可用事件，未找到创建者或精确创建时间。

实施者在09:59尝试启动过Docker Desktop，随后用户也确认Docker已启动。这类启停可能伴随虚拟网络状态变化；未执行修改端口排除的命令，并不能据此断言现象与实施中的环境启停完全无关。当前证据不足确认该次启动与保留段的因果关系。

HNS/WinNAT等虚拟网络组件是排查方向，**目前仅为候选来源**。微软[Winsock错误文档](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)说明10013是访问拒绝，可能涉及独占绑定，故不能单凭10013确定端口排除；本次同时有排除列表与独立绑定探针。[容器网络文档](https://learn.microsoft.com/en-us/virtualization/windowscontainers/container-networking/architecture)说明HNS/WinNAT负责相关网络映射，但其Windows容器说明不能直接证明本机WSL NAT保留段的归属。

## 本次结论与处理边界

此前“55433当前受Windows端口保留限制”的判断有复核依据，**“是谁导致、为什么在此时出现”尚未完全定位**。前次未把这两个结论层次讲清楚，本次明确纠正表达；没有证据指向Agent优化改坏端口配置，不把来源未知掩盖为已找出唯一系统根因。

本次未重启网络服务/修改保留段/变更映射/迁库/删卷，探针无遗留监听，原容器保持停止。0模型/业务调用，四历史脏文件保持。恢复方案应另行确定：可以保持原卷，仅调整宿主映射并同步客户端；或有针对性处理网络组件的运行时保留。65433这里只证明当前可绑定，它仍处于系统动态端口区间，不能承诺永久不再冲突。当前不自动改系统设置或将新测试库冒充原业务库。
