# 商家政策 bundle（合成数据，仅供核心演示）

`bundles/` 下每个文件是一个**不可变版本**的规则集：`bundle_id` 一经导入，内容就不能再变（改了内容再导入会被拒绝，
见 `PolicyImportService`）。版本由受控命令导入校验，没有管理 HTTP 接口（`docs/core-contracts.md:53`）。

```powershell
# 导入（受控命令，不是 HTTP 接口）；库为空时是插入，已存在同内容是幂等跳过
java -jar java/case-service/target/case-service-0.1.0-SNAPSHOT.jar `
  --spring.main.web-application-type=none `
  --resolveflow.policy.import-dir=fixtures/policies/bundles
```

- **选择按支付时间**（本目录原先的约定、`docs/core-contracts.md:50`）：一条订单行走哪个版本，由该行的**支付时间**
  落在哪个 `effective_from`/`effective_to` 区间决定，不按"现在"选，历史订单因此不会被新政策套用。
- 选择规则（C03.1b 修正）：按支付时间取**生效起点最晚**、且未被显式结束的版本。于是
  **无结束日期的版本会被更晚开始的版本取代**——这正是"发布新政策"的含义；若不允许，一个开口的版本就永远无法被
  后继版本取代（后继必然与它重叠），而关闭旧窗口又等于修改一个不可变的版本，政策集就冻住了。
  导入时校验的是"不产生歧义"：同一 `effective_from` 出现两次会被拒绝（同一时刻两套政策无从选择）；
  **起点早于已装版本的**会被拒绝（那是改写历史而不是延续）；**跨越显式结束窗口的**会被拒绝
  （作者说了那版到此为止，别的东西覆盖那一刻就是自相矛盾）。区间之间允许有空隙：政策发布前的支付就是没有政策可用，
  这种情况会被显式拒绝并列出已安装的区间，而不是悄悄套用最近的版本。
- 生效区间是**内部分选择用的**，不在公开响应里：契约的 `PolicyBundle` 只要求 `bundle_id`/`version`/`manifest_hash`/`rules`，
  且 `additionalProperties: false`，所以读取接口不返回区间；读到的正文与导入的原件逐字一致（Java 核验引用要对着原文，
  而不是对着模型的摘要，`docs/core-contracts.md:51`）。

> 目录由 T01 占位、T07 名义上建立；实际由 C03.1 落地：合成两版政策（2026.08 与 2026.09），
> 使"按支付时间选版本"有可验证的新旧两版。C03.1b 把选中的版本钉在工单上（`case_policy_manifest`），
> 之后导入新版本不会改变任何已开工单的政策。