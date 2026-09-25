# 商家政策 bundle（合成数据，仅供核心演示）

`bundles/` 下每个文件是一个**不可变版本**的规则集：`bundle_id` 一经导入，内容就不能再变（改了内容再导入会被拒绝，
见 `PolicyImportService`）。版本由受控命令导入校验，没有管理 HTTP 接口（`docs/core-contracts.md:53`）。

## 文件成员

| 成员 | 必填 | 含义 |
| --- | --- | --- |
| `bundle_id` | 是 | 不可变版本的身份；一经导入不可改内容 |
| `merchant_id` | 是 | **这套政策属于哪个商家**（C07.1）。它是 bundle 身份的一部分：进 `manifest_hash`，也钉在工单上 |
| `version` | 是 | 版本标签（如 `2026.09`） |
| `safety_epoch` | 否 | 缺省 0 |
| `effective_from` | 是 | 生效起点（UTC，必须以 `Z` 结尾） |
| `effective_to` | 是（可 null） | 显式结束；`null` 表示仍生效，会被更晚开始的版本取代 |
| `rules[]` | 是（≥1） | 每条含 `rule_id`/`title`/`text`；`rule_id` 在同一 bundle 内不得重复 |

未知成员一律拒绝（不是忽略）：悄悄丢掉一个拼错的成员，等于作者以为有的规则实际不存在。

## 两个商家（C07.1）

`docs/policy-rag.md:29` 要求**至少 2 商家、2 历史版本、≥20 个规则段落**，所以这里有 4 个 bundle：
`policy-logistics-*` 属于 **M-1001**，`policy-damage-*` 属于 **M-2002**，各有 2026.08 与 2026.09 两版，共 **23 条规则**。

商家过滤**按商家分别判定歧义**：两个商家在同一天各发一版不是冲突（各自的政策集互不相干），
只有**同一商家**在同一时刻出现两版才是歧义，导入会拒绝。选版本时先按商家过滤，再取"生效起点最晚且未被显式结束"的那版
（`PolicySelectionService.selectFor(merchantId, paidAt)`）——在此之前选择是全局的，因此第二个商家根本无法接入。

## 导入与索引是两件事

**这个目录是"受控导入"的输入，不是 Agent 检索的语料。** 导入把文件变成 `policy_bundle`/`policy_rule` 行，
并由 Java 从**已存正文**派生 `manifest_hash` 与每条规则的 `content_hash`。Agent 侧的检索索引由
`scripts/policy_index_ingest.py` 通过 `GET /internal/v1/policies/{bundle_id}`（需要 `policy:read`）拉取
**Java 服务的正文**建立，并原样带上 Java 的 `manifest_hash`——如果 Python 自己解析这些 YAML 来建索引，
"引用校验"就会退化成用它自己算的 hash 验证它自己写的 fixture。

```powershell
# 导入（受控命令，不是 HTTP 接口）；库为空时是插入，已存在同内容是幂等跳过。
# web-application-type=none 不是可选项：PolicyImportCommand 结束时 System.exit，
# 作为 web 服务启动会在 Tomcat 起来几秒后把自己关掉。
java -cp <case-service classpath> com.resolveflow.caseservice.CaseServiceApplication `
  --spring.main.web-application-type=none `
  --resolveflow.policy.import-dir=fixtures/policies/bundles
```

改动这些文件的内容**会改变 `manifest_hash`**，于是旧库里的同 `bundle_id` 版本会与文件不一致而被拒绝
（"version is immutable"）——这是版本机制在起作用。开发期要重新导入，需要先清掉该 bundle 的
`policy_bundle`/`policy_rule` 以及引用它的 `case_policy_bundle`/`case_policy_manifest` 行。

- **选择按支付时间**（本目录原先的约定、`docs/core-contracts.md:50`）：一条订单行走哪个版本，由该行的**支付时间**
  落在哪个 `effective_from`/`effective_to` 区间决定，不按"现在"选，历史订单因此不会被新政策套用。
- 选择规则（C03.1b 修正）：按支付时间取**生效起点最晚**、且未被显式结束的版本。于是
  **无结束日期的版本会被更晚开始的版本取代**——这正是"发布新政策"的含义；若不允许，一个开口的版本就永远无法被
  后继版本取代（后继必然与它重叠），而关闭旧窗口又等于修改一个不可变的版本，政策集就冻住了。
  导入时校验的是"不产生歧义"：同一 `effective_from` 出现两次会被拒绝（**在同一商家内**）；
  **起点早于已装版本的**会被拒绝（那是改写历史而不是延续）；**跨越显式结束窗口的**会被拒绝
  （作者说了那版到此为止，别的东西覆盖那一刻就是自相矛盾）。区间之间允许有空隙：政策发布前的支付就是没有政策可用，
  这种情况会被显式拒绝并列出已安装的区间，而不是悄悄套用最近的版本。
- 生效区间是**内部分选择用的**，不在公开响应里：契约的 `PolicyBundle` 只要求
  `bundle_id`/`merchant_id`/`version`/`manifest_hash`/`rules`，且 `additionalProperties: false`，
  所以读取接口不返回区间；读到的正文与导入的原件逐字一致（Java 核验引用要对着原文，
  而不是对着模型的摘要，`docs/core-contracts.md:51`）。`merchant_id` **在**响应里（C07.1），
  因为检索要先按它硬过滤，Agent 必须能核对"我拉到的这套是不是本 run 商家的"。

> 目录由 T01 占位、T07 名义上建立；实际由 C03.1 落地：合成两版政策（2026.08 与 2026.09），
> 使"按支付时间选版本"有可验证的新旧两版。C03.1b 把选中的版本钉在工单上（`case_policy_manifest`），
> 之后导入新版本不会改变任何已开工单的政策。C07.1 加了 `merchant_id`（进 hash 与工单钉子）与第二个商家，
> 并把语料扩到 23 条规则，使商家/版本过滤可以被证伪而不是被声明。