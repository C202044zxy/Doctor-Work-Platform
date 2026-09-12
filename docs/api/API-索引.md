# 医生工作平台 · API 接口索引

> 版本 v1.0 ｜ 2026-09-11 ｜ 维护人：C（葛航）
> 机器可读契约见同目录 [`openapi.yaml`](openapi.yaml)。
> 本文档是**接口清单 + 中文说明**，供后端同学按模块实现；`openapi.yaml` 是精确的字段级契约。

---

## 0. 这份文档怎么用

- **后端同学**：找到你负责的任务 ID（见每节的"任务"列），按表格里的路径和请求/响应体实现。字段类型以 `openapi.yaml` 为准。
- **前端同学**：`openapi.yaml` 可以直接喂给 mock 工具生成假数据；页面与接口的对照见 [§3](#3-前端页面--接口对照)。
- **本文与其它文档冲突时以本文为准**（团队 2026-09-11 决议），理由见 [§4](#4-需要改造的现有实现)。

**标记约定**

| 标记 | 含义 |
|---|---|
| 🔴 P0 | 签收标准里的 P0；不通过则该任务**整体不予签收** |
| 🟡 P1 | 应有功能 |
| ⚪ P2 | 可裁剪；全项目唯一可整体砍掉的缓冲 |
| ✂️ | 老师原始需求中**已明确砍掉**，不在本期范围 |

---

## 1. 全局约定

### 1.1 前缀

所有业务接口以 `/api` 开头。唯一例外是健康检查（见 §2.1 的说明）。

### 1.2 统一响应结构

**成功**

```json
{ "code": 0, "message": "ok", "data": { } }
```

**失败**（HTTP 状态码与 `code` 一致）

```json
{ "code": 404, "message": "Patient not found", "data": null }
```

- `code = 0` 表示成功，非 0 即为错误码。
- `message` 默认是**给开发者看的英文短句**，前端不直接展示给用户，只用于排查；前端展示自己的英文文案。（全站英文，见课堂要求。）
- **一处例外**：医嘱校验的 `messages[]`（见 §2.4）**必须原样展示给用户**。签收标准 T23 第 5 条要求"弹窗文案与后端返回的校验详情一致，不另写一套文案"——即弹窗里的"该患者对【青霉素类】过敏，禁止开立"就是后端那句话，前端不得改写。这是**唯一**允许前端直出 `message` 的地方。
- `data` 失败时为 `null`，前端可以无条件读 `res.data.data`。
- 这是**服务端强制**的：由全局异常处理器统一包装，路由函数只管返回裸数据。

### 1.3 分页

**请求**（query 参数，所有列表接口统一）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page` | int | `1` | 页码，从 1 开始 |
| `size` | int | `20` | 每页条数，上限 100 |

**响应**

```json
{
  "code": 0,
  "message": "ok",
  "data": { "items": [], "total": 0, "page": 1, "size": 20 }
}
```

- `total` 是**满足筛选条件的总条数**，不是当前页条数。
- 空结果返回 `items: []`、`total: 0`，**不是 404**。

### 1.4 认证

- 登录成功后由 `Authorization: Bearer <access_token>` 携带。
- JWT，**有效期 2 小时**；登出后 `jti` 进 Redis 黑名单，立即失效。
- 登录是**两步**：`POST /api/auth/login` 校验密码返回一次性 `ticket` → `POST /api/auth/verify-code` 提交邮箱验证码换 JWT。两步之间的 `ticket` 有效期 5 分钟。
- 需要认证的接口在表中标 **🔒**；标注了角色的在 `角色` 列写明。
- **三种 401 的 `message` 必须可区分**（T05 第 5 条）：无 token / token 过期 / token 在黑名单。前端据此给不同提示。
- `status = disabled` 的用户即使持有**有效 token** 也被拒绝（同样是 401）。
- **登录失败限速**：同一账号连续 5 次密码错误必须被锁定/限流，不得无限重试（T05 S2）。

### 1.5 角色与数据范围

**功能权限**（角色决定"能做什么"）

| 角色代码 | 含义 | 说明 |
|---|---|---|
| `admin` | 管理员 | 用户管理、模板维护、全部数据、审计日志、临时授权 |
| `senior` | 主任医师 | 病历审阅/归档、临时授权、本科室数据 |
| `junior` | 住院医师 | 写病历、开医嘱，**看不到**审阅队列/审计日志/用户管理 |

> 后端 `seed.py` 目前是 `administrator`/`doctor`/`department_manager`，**必须改成上面三个**。
>
> ⚠️ **JWT payload 里的字段名是 `title`，不是 `role`**（T05 第 3 条原文：payload 含 `user_id` / `title` / `department` / `jti`）。前端读当前角色要读 `user.title`。接口返回的用户对象同样用 `title`。

**数据权限**（科室决定"能看谁"）

- 医生只能看到**自己科室**的患者、病历、问诊、会诊。
- `admin` 不受科室限制。
- `temp_grant`（临时授权）是唯一的限时例外：**`admin` / `senior` 可发起**（T10 第 1 条），为一个具体**患者**授予跨科室访问，到期自动失效，访问回落为 404。
- 过滤逻辑必须在 **service 层统一入口**实现，不是每个路由各写一遍（T09 第 3 条，代码评审项）。

**权限失败分两种口径，不要混用**（签收标准 T08 S2 + T09）：

| 情形 | 返回 | 理由 |
|---|---|---|
| **角色功能权限不足**：该角色根本不能做这个动作（如 `junior` 调审阅接口） | **403**，`message` 指明缺少的权限 | 动作本身对该角色不可见，不涉及数据 |
| **数据范围外**：动作允许，但对象属于别的科室 | **404**，与"真的不存在"完全同口径 | 不泄露"该患者存在"这一事实 |

签收场景 S2 会直接验这条：`dr_wang`（junior）调 `GET /api/patients/P20260003`（神经内科患者）**必须返回 404，返回 403 即不签收**。

所以"返回 404 还是 403"取决于**是角色不够还是科室不够**，不是"越权一律 403"。

### 1.6 错误码

| code | 场景 |
|---|---|
| 0 | 成功 |
| 401 | 未登录 / token 过期 / 已在黑名单（三者 `message` 可区分）；`status=disabled` |
| 403 | 角色不具备该功能权限（如 `junior` 调审阅接口、非参与人下载会诊资料） |
| 404 | 资源不存在，**或超出本科室数据范围**（两者同口径，不区分） |
| 409 | **归档锁定**（对 `archived` 病历的任何修改，T19/T24）、乐观锁版本不一致、重复加入分组、**医嘱过敏拦截**（T21）、**会诊状态机非法跳转**（T30） |
| 422 | 参数校验失败，`message` **指出具体字段名** |
| 429 | 验证码发送过于频繁（**响应含剩余秒数**）、登录密码连续错误锁定 |
| 500 | 未捕获异常 |

**⚠️ 两条容易搞错的**：

1. **归档锁定是 409，不是 400。** 签收标准 T19 第 3 条与 T24 第 4 条都写的是 409（"任何修改接口对归档病历返回 409 并提示'已归档，不可修改'"）。
2. **健康检查永远不会返回 5xx。** T03 第 1 条明确："Redis 断连时**仍返回 200** 且标识 `redis:"down"`，**不得 500 崩溃**"。依赖挂了不改变状态码，只在 body 里体现。因此**本表没有 503**。

`409` 与 `422` 在医嘱拦截上**两者都被签收标准接受**（T21 第 1 条原文写"返回 422/409"）；本契约统一取 **409**，理由是"拦截是状态冲突而非参数格式错误"。

### 1.7 枚举值（前后端必须一致）

| 字段 | 取值 | 出处 |
|---|---|---|
| `title`（**不是 `role`**） | `admin` / `senior` / `junior` | T05 §3 |
| `gender` | `male` / `female` / `unknown` | — |
| `allergy.allergy_type` | `drug` / `food` / `other` | T14 §1 |
| `allergy.severity` | `mild` / `moderate` / `severe` | T14 §1 |
| `record.status` | `draft` / `pending` / `rejected` / `archived` | T19 §1 |
| `emr_field.type` | `text` / `number` / `date` / `select` / `textarea` | T18 §1 |
| `order.order_type` | `drug` / `lab` / `exam` | T20 §1 |
| `order.status` | `active` / `stopped` | T20 §2 |
| `order.validation_status` | `passed` / `warning` / `blocked` | T20 §3 |
| `order.validation_detail[].kind` | `allergy` / `dose` | T21 §1 |
| `consultation.status` | `waiting` / `active` / `ended` | — |
| `message.sender_type` | `doctor` / `patient_assist` | — |
| `meeting.status` | `requested` / `accepted` / `declined` / `in_progress` / `completed` | T30 §1 |
| `meeting.participants[].status` | `invited` / `accepted` / `declined` | T30 §3 |
| `vital.sign_type` | `bp` / `gl` / `hr` | T33 §1 |
| `vital.source` | `manual` / `mock` | T33 §2 |
| `reminder.rtype` | `medication` / `followup` / `checkin` | T36 §1 |
| `health_plan.status` | `active` / `completed` / `terminated` | T35 §4 |
| `health_plan.entries[].kind` | `medication` / `followup` / `diet_exercise` | T35 §1 |
| `meeting_report.status` | `draft` / `final` | T32 §2 |
| `review.decision` | `approve` / `reject` | T19 §3 |
| `user.status` | `active` / `disabled` | T05 §4 |
| `audit_log.result` | `success` / `failure` | T11 §1 |

**改动说明**（相对初稿）：

- `role` → `title`（T05 原文）。
- `vital.type` 的 `glucose`/`heart_rate`/`weight` → `gl`/`hr`，**`weight` 不在签收范围内**（T33 只要求 bp/gl/hr）。
- `meeting.status` 补 `declined`，并**去掉初稿多写的 `archived`**（T30 状态机止于 `completed`）。
- 模板字段类型去掉 `checkbox`（T18 只列 5 种）。
- `order.status` **去掉 `modified`**：T20 §2 的停用是软停用（`status` → `stopped`，行保留），改单并不改变状态，它记在审计里，不是第三态。
- `order.validation_detail[].kind` **去掉 `duplicate`**：T21 的三级检查只有"过敏命中"和"剂量超范围"两种会触发，其余是 `passed` 且 `reasons` 为空，没有第三种。
- 其余 7 组在此**补录**（它们一直在契约里，只是本表漏列，导致 §1.7 与实际枚举对不上）。

### 1.8 时间与脱敏

- 时间统一 **ISO 8601 UTC**，例如 `2026-09-11T02:30:00Z`。前端负责转本地时区展示。
- 手机号、身份证等敏感字段：列表接口返回**脱敏后**的值（`138****1234`）；详情接口按角色决定是否返回明文。字段名带 `_enc` 表示库中加密存储。

---

## 2. 接口清单

### 2.1 基建

> 任务 T03（负责人 **B**）。🔴 P0

| 方法 | 路径 | 说明 | 任务 | 负责人 |
|---|---|---|---|---|
| GET | `/api/health` | **恒返回 200**，body 为 `{code:0, data:{db, redis}}` | T03 | **B** |
| GET | `/health` | 上面那条的**同函数别名**，响应逐字节相同；签收场景调的就是这个路径 | T03 | **B** |

**关键约束：健康检查永远不返回 5xx。** T03 第 1 条原文——

> `GET /health` 返回 `{code:0, data:{db:"ok", redis:"ok"}}`；**Redis 断连时仍返回 200 且标识 `redis:"down"`，不得 500 崩溃**。

`db` / `redis` 各取 `ok` / `down` / `disabled`（`disabled` = 该依赖未配置 URL）。**依赖挂掉只改 body，不改状态码**——这样负载均衡与 CI 探针不会因为 Redis 抖动把整个应用判死。

**路径别名（已定）**

签收标准 T03 写的是 `GET /health`（不带 `/api`），仓库约定是"所有路由在 `/api` 下"（`README.md`、`AGENTS.md`）。两边都保留：`/api/health` 为主路由，`/health` 注册同函数的别名，**响应必须完全一致**。签收场景 S1 调用的是 `/health`，所以别名不是可选项——只挂 `/api/health` 会让 T03 签不掉。

> 现有的 `/api/health/live` 和 `/api/health/ready` 保留不动（CI 的 `smoke.py` 依赖它们），只是**不作为签收依据**。
>
> ⚠️ 注意：`live`/`ready` 两个老接口的语义是"依赖不健康就返回非 200"，与 T03 的"永远 200"**正好相反**。两者并存时不要误把老接口当成签收对象。

> **负责人更正**：T03 在 `project_plan.md` 与签收标准里都归 **B**（初稿误写为 A）。

---

### 2.2 M1 安全账户登录

> 任务 T05/T10 归 **A**；T06/T08/T09 归 **B**。🔴 P0

#### 认证流程

| 方法 | 路径 | 🔒 | 角色 | 说明 | 任务 |
|---|---|---|---|---|---|
| POST | `/api/auth/login` | — | — | 提交 `username` + `password`，校验通过返回一次性 `ticket`（5 分钟）；密码错误 401，**连续 5 次锁定** | T05 |
| POST | `/api/auth/send-code` | — | — | 用 `ticket` 换发邮箱验证码；**60 秒内限一次**、单账号单日上限 20 次，超限 429 且**响应带剩余等待秒数** | T06 |
| POST | `/api/auth/verify-code` | — | — | 提交 `ticket` + `code`，成功返回 `access_token` 与用户信息；错误 401 | T05 |
| POST | `/api/auth/logout` | 🔒 | 任意 | `jti` 进 Redis 黑名单，立即失效 | T05 |
| GET | `/api/me` | 🔒 | 任意 | 当前用户信息：`id` / `username` / `name` / **`title`** / `department` | T05 |

**验证码的四条硬约束**（T06，容易漏）：6 位数字、Redis **TTL = 300s**、**一次性**（用过即废，二次提交失败）、**绝不出现在任何响应体与日志中**。SMTP 不可用时必须返回明确错误、**不吞异常**。

**`POST /api/auth/login` 请求**

```json
{ "username": "dr_li", "password": "…" }
```

**`POST /api/auth/verify-code` 响应 `data`**

```json
{
  "access_token": "eyJ…",
  "token_type": "bearer",
  "expires_in": 7200,
  "user": {
    "id": 2,
    "username": "dr_li",
    "name": "李医生",
    "title": "senior",
    "department": "心血管内科"
  }
}
```

#### 用户管理（仅 `admin`）

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/users` | `admin` | 列表，支持 `q`（姓名/账号）、**`title`**、`department` 筛选 + 分页 | T08 |
| POST | `/api/users` | `admin` | 创建用户（`username`/`password`/`name`/`email`/`title`/`department` 均必填） | T08 |
| GET | `/api/users/{id}` | `admin` | 详情 | T08 |
| PATCH | `/api/users/{id}` | `admin` | 改 **`title`** / `department` / `status` / `name`（全选填） | T08 |
| GET | `/api/roles` | 🔒 任意 | 角色字典（返回三个角色代码与显示名） | T08 |
| GET | `/api/departments` | 🔒 任意 | 科室字典（**已有**）。**契约里唯一不挂任务 ID 的接口**——它先于任务表存在，也没有任何签收条目约束它，所以不编任务号，契约中直接写明这一点 | 已有 |

> ⚠️ 上面这组 `/api/users` CRUD **在 44 个任务里没有明确归属**。T08 的验收标准第 3 条只把"用户管理"列为**受保护资源**（即权限矩阵要覆盖它），并没有说谁来实现这套 CRUD。
> 返回的"任务"列写 T08 是我的推断（因为权限矩阵要覆盖它），**需要 B 确认**。对应的前端用户管理页则完全没有任务。

#### 临时授权 temp_grant

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/temp-grants` | `admin`/`senior` | 列表 | T10 |
| POST | `/api/temp-grants` | **`admin`/`senior`** | 发起授权 | T10 |
| DELETE | `/api/temp-grants/{id}` | `admin`/`senior` | 手动立即失效（演示"权限收回"；T30 会诊结束时调用） | T10 |

**表结构（T10 第 1 条原文照抄）：`temp_grant(grantee_id, patient_id, reason, expire_at, is_valid)`**

没有 `target_type`、没有 `target_id`、没有 `duration_hours`、没有 `expires_at`（是 `expire_at`），也没有 `status` 枚举——**有效期只由 `expire_at` 表示，有效性只由 `is_valid` 布尔表示**。

> ⚠️ 上表里 T10 写的 `patient_id` 是**库表内部键**；接口层一律用患者的业务键 `patient_no`（`P20260001`），请求与响应里都不会出现 `patient_id`。同理 `medical_order` 与 `vital_sign` 的表结构注释里也是 `patient_id`，接口字段是 `patient_no`——两者不是同一个东西，不要照抄表结构当接口字段名。

**`POST /api/temp-grants` 请求**

```json
{
  "grantee_id": 3,
  "patient_no": "P20260001",
  "expire_at": "2026-09-12T02:30:00Z",
  "reason": "跨科室会诊需要"
}
```

- 授权对象**只有患者**（`patient_no`），不支持"病历/会诊"等其它类型。
- **`expire_at` 由调用方给定，不是后端用时长算出来的。** T30 自动建授权时也是后端直接算出"预计会诊时间 + 24h 缓冲"填进来。

> 演示要点：授权到期后该用户访问目标患者必须**回落到 404**（不是 403），不需要重启服务。APScheduler 每分钟扫描 `expire_at < now() AND is_valid = 1` → 置 `is_valid = 0`。
> 审计记录两条：`temp_grant.create` 与 `temp_grant.expire`。任务**随应用启动注册一次**，不重复注册。

---

### 2.3 M2 患者信息管理

> 任务 T13/T14 归 **D**；T15/T16 归 **C**；T17 前后端各半（**D + C**）。🟡 P1

#### 患者

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients` | 列表 + 多条件搜索 + 分页，见下 | T13 |
| POST | `/api/patients` | 新建。**`patient_no` 由系统生成且唯一，请求体不接受该字段** | T13 |
| GET | `/api/patients/{patient_no}` | 详情（含过敏史、分组） | T14 |
| PATCH | `/api/patients/{patient_no}` | 编辑基础信息（**现有后端缺此接口**） | T13 |
| DELETE | `/api/patients/{patient_no}` | 删除。**删除策略（软删/级联）须写进接口文档** | T13 |

> `patient_no` 系统生成（T13 第 1 条），格式如 `P20260001`。前端**不能在新建表单里填患者号**——这是初稿漏掉的一处契约差异。

**`GET /api/patients` query 参数**

| 参数 | 类型 | 说明 |
|---|---|---|
| `name` | string | 姓名**模糊**匹配 |
| `patient_no` | string | 患者号**精确**匹配（不是模糊） |
| `symptom_tags` | string[] | 症状标签匹配 |
| `admitted_from` / `admitted_to` | date | 入院日期区间 |
| `department` | string | 科室筛选（非 admin 时强制为本人科室） |
| `group_id` | int | 按分组筛选 |
| `page` / `size` | int | 分页 |

> **四个搜索条件必须可任意 AND 组合**（T13 第 2 条）：姓名模糊、`patient_no` 精确、`symptom_tags` 匹配、入院日期区间。四条件全空 → 返回全量分页。
> 默认按 `created_at` 倒序（T13 第 3 条）。

**`GET /api/patients` 单条 `items[]` 结构**

```json
{
  "patient_no": "P20260001",
  "name": "赵大勇",
  "gender": "male",
  "birth_date": "1968-03-12",
  "phone_masked": "138****1234",
  "department": "心血管内科",
  "symptom_tags": ["胸痛", "高血压"],
  "allergy_count": 2,
  "has_severe_allergy": true,
  "created_at": "2026-09-01T08:00:00Z"
}
```

> `has_severe_allergy` 是**给列表页红色角标用的**，不要前端自己遍历过敏数组算。

**`GET /api/patients/{patient_no}` 详情额外返回**

```json
{
  "id_card_masked": "110***********1234",
  "allergies": [
    { "id": 1, "allergen": "PENICILLIN", "allergy_type": "drug", "severity": "severe", "recorded_at": "2026-08-01" }
  ],
  "histories": [
    { "id": 1, "diagnosis": "2型糖尿病", "onset_date": "2019-05-01", "notes": "…" }
  ],
  "groups": [ { "id": 1, "name": "慢病随访" } ]
}
```

#### 病史

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/histories` | 病史列表（时间线用，按 `onset_date` 倒序） | T14 |
| POST | `/api/patients/{patient_no}/histories` | 新增 | T14 |
| PATCH | `/api/histories/{id}` | 修改 | T14 |
| DELETE | `/api/histories/{id}` | 删除 | T14 |

#### 过敏史

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/allergies` | 过敏列表 | T14 |
| POST | `/api/patients/{patient_no}/allergies` | 新增 | T14 |
| PATCH | `/api/allergies/{id}` | 修改 | T14 |
| DELETE | `/api/allergies/{id}` | 删除 | T14 |
| GET | `/api/allergens` | 过敏原字典（至少覆盖：**青霉素类、磺胺类、头孢类、阿司匹林、造影剂**，支持自定义补充） | T14 |

**过敏记录字段**（T14 第 1 条）：`allergen`、`allergy_type`、`severity`、`recorded_at`。

- 过敏**增/删/改均写审计**（`allergy.delete` 等，记被删过敏原名称）。
- 删除患者时过敏记录的**级联策略要明确**（T14 第 4 条）。
- 详情接口返回的这份过敏列表**同时供前端警示条和 T21 校验引擎消费**——同一数据源，不许各查各的（T14 第 2 条）。后端需提供标准函数 `get_patient_allergens(patient_no)`。

#### 患者分组

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patient-groups` | 分组列表（含每组人数） | T17 |
| POST | `/api/patient-groups` | 创建分组（按病种 / 管理状态） | T17 |
| PATCH | `/api/patient-groups/{id}` | 重命名 | T17 |
| DELETE | `/api/patient-groups/{id}` | 删除 | T17 |
| POST | `/api/patient-groups/{id}/members` | 批量加入，体 `{"patient_nos": ["P20260001"]}` | T17 |
| DELETE | `/api/patient-groups/{id}/members` | 批量移出，同上 | T17 |

---

### 2.4 M4 电子病历 ⭐（最高分模块）

> 任务 T18/T19/T21/T24 归 **A**；T20 归 **B**；T22/T23 归 **C**。🔴 P0

#### 病历模板

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/templates` | 🔒 任意 | 模板列表 | T18 |
| POST | `/api/emr/templates` | `admin` | 新建模板 | T18 |
| GET | `/api/emr/templates/{id}` | 🔒 任意 | 详情，**含 `fields_json`** | T18 |
| PATCH | `/api/emr/templates/{id}` | `admin` | 修改 | T18 |

**`fields_json` 的结构（前端动态表单的唯一依据）**

```json
{
  "fields": [
    { "key": "chief_complaint", "label": "Chief complaint", "type": "text",     "required": true },
    { "key": "history",         "label": "History",         "type": "textarea", "required": false },
    { "key": "severity",        "label": "Severity",        "type": "select",   "required": true,
      "options": ["mild", "moderate", "severe"] }
  ]
}
```

支持的 `type`：**`text` / `number` / `date` / `select` / `textarea` —— 只有这 5 种**（T18 第 1 条原文）。不做通用表单引擎（风险 R6 的缓解措施）。

> ⚠️ 初稿把 `checkbox` 也列了进去，**签收标准里没有这一种**。

**其他要点**
- 表结构 `emr_template(id, name, fields_json, is_active)`；**停用走 `is_active`**，不是删除。
- 需**2 个预置模板**：「入院记录」「日常病程记录」，字段数各 ≥ 6。
- 模板**停用后不影响已有病历**——历史病历按当时模板渲染（T18 第 4 条）。
- 仅 `admin` 可维护；变更写审计 `emr_template.*`。

#### 病历

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/records` | 🔒 | 列表，支持 `patient_no` / `status` / `author_id` 筛选 + 分页 | T19 |
| POST | `/api/emr/records` | `senior`/`junior` | 新建草稿 | T19 |
| GET | `/api/emr/records/{id}` | 🔒 | 详情，含 `content_json`、`status`、`version` | T19 |
| PATCH | `/api/emr/records/{id}` | 作者 | 保存草稿，**带 `version` 做乐观锁** | T22 |
| POST | `/api/emr/records/{id}/submit` | 作者 | 提交审阅：`draft` → `pending` | T19 |
| GET | `/api/emr/records/{id}/versions` | 🔒 | 版本历史 | T19 |
| POST | `/api/emr/records/{id}/amend` | **作者** | 对**已归档**病历追加补记（不修改原文）。**不是 `senior` 专属**——T19 S2 里补记的人正是 `dr_wang`（junior） | T19 |

**`PATCH` 请求体**

```json
{ "content_json": { "chief_complaint": "…" }, "version": 3 }
```

- `version` 不匹配返回 **409**，前端提示"病历已被他人修改，请刷新"。
- 目标病历 `status = archived` 时返回 **409**（归档锁定，只读）——**不是 400**。两个 409 用 `message` 区分。
- 版本号每次提交 **+1 并存全量快照**（不是只存差异）；可查历史版本列表并按版本号查看内容。
- 病历内容按模板 `fields_json` 校验，必填项缺失 → **422 且指出字段名**。
- 归档后的修订只能走**「补记」**（新增关联版本，原版本内容不变），不能改原文。
- **保存失败不得丢失用户已输入内容**——这是 T22 的 P0 验收项，前端要保留草稿（本地暂存）。

#### 医嘱

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/emr/orders` | 按 `record_id` 查医嘱列表 | T20 |
| POST | `/api/emr/orders` | 开立医嘱（**保存前必须过校验**，见下） | T20 |
| PATCH | `/api/emr/orders/{id}` | 修改 | T20 |
| POST | `/api/emr/orders/{id}/stop` | 停止医嘱 | T20 |
| POST | `/api/emr/orders/validate` | **只校验不保存**，供前端实时预检 | T21 |
| GET | `/api/drugs` | 药品字典（含 `contraindications` 过敏原标签） | T21 |

**`POST /api/emr/orders/validate` 请求**

```json
{
  "patient_no": "P20260001",
  "items": [
    { "order_type": "drug", "drug_code": "AMOX500", "dose": "0.5g", "frequency": "tid" }
  ]
}
```

> ⚠️ 医嘱项的字段名是 **`order_type`**，不是 `type`（与 `Order.order_type` 同名同枚举，这样开立后原样读回）。`POST /api/emr/orders`（保存型）的请求体是 `{"record_id", "items"}`——**这条不带 `patient_no`**，患者由 `record_id` 所属病历推出，服务端必须据此取过敏原再校验；带 `patient_no` 的是上面这条**只校验不保存**的 `/validate`。

**响应 `data`**

```json
{
  "overall": "blocked",
  "results": [
    {
      "index": 0,
      "status": "blocked",
      "reasons": [
        { "kind": "allergy", "severity": "severe", "allergen": "PENICILLIN",
          "message": "Patient has a severe penicillin allergy" }
      ]
    }
  ]
}
```

**三级校验语义（演示核心，必须严格实现）**

| `status` | 触发条件 | 前端表现 | 能否保存 | HTTP |
|---|---|---|---|---|
| 🔴 `blocked` | 药品与患者过敏原冲突 | 红色弹窗，**只有"取消"/"更换药品"，没有"强制开立"** | **禁止，不写库** | **409** |
| 🟡 `warning` | 剂量超出常规范围 | 黄色弹窗，"确认继续"，理由**可选填** | 可保存（有理由则记） | 200 |
| 🟢 `passed` | 无冲突 | 无弹窗 | 可保存 | 200 |

- **两类校验可同时命中，并按严重度排序展示**（T21 第 3 条）；校验规则**配置化**，不硬编码在业务代码里。
- **红色弹窗绝不能有强制开立的出口**——这是 T23 的 P0 验收项，也是答辩卖点。校验必须在**服务端**再做一遍，绕过前端直接调 API 仍被拦截。
- 🟡 警告的文案要**带常规范围**（"常规剂量 20–40mg/日，当前 80mg"），🔴 拦截的文案要**带过敏原名**（"该患者对【青霉素类】过敏，禁止开立"）。
- **这两种文案前端原样展示，不要自己改写**（T23 第 5 条），见 §1.2 的例外说明。
- 每条医嘱落库时留存 `validation_status` 与**校验详情**（命中了哪条规则），并写审计。
- **开立 / 改单 / 停用三个动作各写一条审计**，动作名分别是 `medical_order.create` / `medical_order.modify` / `medical_order.stop`。T20 场景 S2 的原文是"查审计日志可见 **create / modify / stop 三条记录**"——**初稿只写了 modify 和 stop，漏了 `create`**，照它生成代码的话 S2 只能查到两条。
- **药品项缺 `dose` → 422 并指明字段**（T20 场景 S2："未填写剂量 → 422 且指明字段"）。契约没有把 `dose` 写成全局必填，因为 `lab`/`exam` 项本来就没有剂量；规则是**按 `order_type` 条件生效**：`drug` 项必须有 `dose`，其余不受这条约束。

#### 审阅与归档

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/reviews` | `senior` | 待审队列（`status = pending`，按提交时间排序） | T24 |
| POST | `/api/emr/records/{id}/review` | `senior` | 审阅：`{"action":"approve"\|"reject","comment":"…"}` | T24 |
| GET | `/api/emr/my-submissions` | 🔒 作者本人 | "我的提交"：作者查看自己的病历及**退回意见** | T24 |
| POST | `/api/emr/records/{id}/archive` | `senior` | 归档 → 只读 | T24 |

- **`approve` 之后直接 `archived`，中间没有 `approved` 状态。** T24 第 2 条原文："**通过 → 归档**：状态置 `archived`，写入 `reviewer_id` / `reviewed_at`，病历转为只读。"（初稿的"或 `approved` 再由归档步骤处理"是多余的，已删除——T24 已拍板。）
- `reject` 必须带 `comment` → `status` → `rejected` 并保存 `review_comment`；作者在"我的提交"里能看到该意见，修改后**重新提交（版本 +1，重新进 `pending`）**。
- **归档后任何修改接口一律 409**，这是 T24 的 P0 验收项（前端编辑器同时置只读态，双保险）。
- 审阅动作（通过/退回）写审计，含审阅人、时间、意见。
- `junior` **看不到待审列表**（RBAC），但**能看自己的"我的提交"**——这是两个不同的列表，别合并成一个。

---

### 2.5 M3 在线问诊

> 任务 T25/T26/T27 归 **B**；T28 归 **D**；T29 归 **A**。
> ⚠️ **M3 没有任何任务归 C** —— 包括聊天室 UI 在内的整个问诊工作台都记在 B 名下（签收标准 T27）。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/consultations` | 🔒 | 列表，按 `status` 分组（`waiting`/`active`/`ended`）+ 分页；每条带 `last_message` / `last_message_at`（工作台列表要显示"最后一条消息"） | T27 |
| POST | `/api/consultations` | `junior`/`senior` | 接诊/发起 | T27 |
| GET | `/api/consultations/{id}` | 🔒 | 详情 | T27 |
| POST | `/api/consultations/{id}/accept` | 🔒 | 接诊：`waiting` → `active` | T27 |
| POST | `/api/consultations/{id}/end` | 🔒 | 结束：`active` → `ended` | T27 |
| GET | `/api/consultations/{id}/messages` | 🔒 | 历史消息（分页，倒序） | T26 |
| POST | `/api/consultations/{id}/messages` | 🔒 | 发消息（**HTTP 兜底**，正常走 WebSocket） | T26 |
| GET | `/api/consultations/records` | 🔒 | 检索历史问诊（按患者/日期/关键词） | T28 |
| GET | `/api/consultations/export` | 🔒 | 导出 CSV | T28 |
| POST | `/api/uploads/images` | 🔒 | 上传图片，`multipart/form-data`，返回 `{"url":"/uploads/…"}` | T26 |
| GET | `/api/consultations/{id}/calls` | 参与人 | 通话记录列表（分页、倒序）；**"可在问诊记录中查看"就靠这条**（T29 第 3 条） | T29 |
| POST | `/api/consultations/{id}/calls` | 参与人 | 记录一次通话的元数据（发起/接通/结束时间、时长）。**通话结束后才写**，非参与人 403 | T29 |
| WS | **`/ws/chat/{room_id}`** | 🔒 | 实时图文消息（房间 = `consultation_id` 或 `meeting_id`） | T25 |

**上传图片的四条硬约束**（T26 第 2 条，安全项，容易被跳过）：

1. 类型白名单 **jpg / png / webp**，且按**内容类型**校验（改扩展名的 `.exe` 必须被拒）
2. 大小上限 **≤ 5MB**
3. **文件名重命名为随机值**——防覆盖与路径穿越（上传 `../evil.png` 后不得逃逸出 `uploads/`）
4. `uploads/` 目录不进 Git，且有定期清理策略说明

> ⚠️ **WebSocket 路径是 `/ws/chat/{room_id}`，不是 `/ws/consultations/{id}`。** T25 第 1 条原文写的是 `WebSocket 路由（如 /ws/chat/{room_id}）`；且第 2 条说房间号可以是 `consultation_id` **或 `meeting_id`**——所以路径里是通用的 `room_id`，问诊和会诊**复用同一个路由**，不各开一条。
> 连接时**校验 JWT，无效 token 拒绝握手**。异常断开要清理在线状态（不残留"幽灵在线"）。

**WebSocket 消息信封**

```json
{ "type": "message", "data": { "id": 1024, "sender_type": "doctor", "content": "…", "image_url": null, "sent_at": "…" } }
```

`type` 取值：`message` / `typing` / `joined` / `left` / `call_offer` / `call_answer` / `ice_candidate`。

> **广播的 `data` 必须带持久化后的 `id`。** T27 第 2 条要求聊天气泡有"**发送中/已送达**"两态：客户端先乐观渲染一条"发送中"的气泡，收到带同一个 `id` 的回显后才把它置为"已送达"。没有 `id` 就没法把回显和本地气泡对上，这个状态机做不出来。

> **信令房间要校验参与者。** T29 第 5 条要求"**非参与者无法接入信令房间**"——只有该会话的参与医生能发起/接听。握手里 JWT 有效但不在会诊/会诊名单上的人，应在升级完成前拿到 **403**。只写 `/calls` 的 403 不够：信令走的是 WS，得在 WS 上也挡住。

> WebRTC 信令复用同一个 WebSocket 房间（最后三个 `type`），**不单独开信令服务**。
> ✂️ 云端录像、自动录像**已砍**，`/calls` 只记录元数据（时长、起止）。

---

### 2.6 M5 远程会诊

> 任务 T30/T31/T32 **全部归 D**（T32 含"列表/详情前端"和打印页）。
> ⚠️ **M5 没有任何任务归 C。**

**状态机**：`requested` → `accepted` → `in_progress` → `completed`，另有 `declined` 分支（T30 第 1 条）

> ⚠️ **没有 `archived` 状态。** 被归档的是**报告**（落到患者档案），不是会诊本身（T32 第 3 条）。初稿多写了 `archived`。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/meetings` | 🔒 | 列表（我发起的 + 邀请我的），按 `status` / **`patient_no`** 筛选 | T30 |
| POST | `/api/meetings` | **`junior`/`senior`** | 发起会诊：选患者 + 选专家（可多选）+ 填**目的**（`purpose`，**必填**）；`scheduled_at` **可选**（不填则由后端取当前时刻）；`title` 可选（不填由 `purpose` 派生） | T30 |
| GET | `/api/meetings/{id}` | 参与人 | 详情 | T30 |
| POST | `/api/meetings/{id}/accept` | 被邀者 | 接受邀请：`requested` → `accepted` | T30 |
| POST | `/api/meetings/{id}/decline` | 被邀者 | 拒绝邀请：`requested` → `declined` | T30 |
| POST | `/api/meetings/{id}/start` | 发起人 | `accepted` → `in_progress` | T30 |
| POST | `/api/meetings/{id}/complete` | 发起人 | `in_progress` → `completed` | T30 |
| GET | `/api/meetings/{id}/participants` | 参与人 | 参与人列表及接受状态 | T30 |
| GET | `/api/meetings/{id}/materials` | 参与人 | 资料列表 | T31 |
| POST | `/api/meetings/{id}/materials` | 参与人 | 上传病历/影像（`multipart`） | T31 |
| GET | `/api/materials/{id}/download` | 参与人 | 下载资料 | T31 |
| GET | `/api/meetings/{id}/report` | 参与人 **或**能触达该患者的同科室医生 | 会诊报告（归档后从患者档案可读） | T32 |
| POST | `/api/meetings/{id}/report` | **参与人** | 生成/保存报告（T32 S2 要让非参与医生拿 403） | T32 |
| GET | `/api/meetings/{id}/report/print` | 参与人 | 返回可打印的 HTML（Jinja2 渲染） | T32 |

- **发起人可以是 `junior`。** T30 的演示场景 S1 原文就是"**`dr_wang` 对 `P20260001` 发起会诊邀请 `dr_chen`**"，而 `dr_wang` 是 junior。初稿把发起限死为 `senior`，**会让流程 2 的演示跑不起来**。
- **状态机非法跳转返回 409**（如 `requested` 直接跳 `completed`）。
- 非受邀人访问该会诊 → 403/404，不泄露存在性。
- 会诊发起/接受/状态变更均写审计。
- **`scheduled_at` 不是必填。** T30 第 2 条列的入参只有"患者 + 专家 + 目的"，所以前端不传时间也必须能发起；不传时后端按当前时刻落库。它唯一的额外作用是为每位受邀专家算 `temp_grant` 的有效期（该时刻 + 24h）。
- **"目的"是必填的 `purpose`，不是可选的 `description`。** T30 第 2 条把目的列为三个入参之一，第 4 条又要求详情把它显示出来——所以它必须既**必填**又**能读回**。初稿把它写成可选的 `description` 且响应体里根本没有这个字段，结果是"照着 T30 的三项发文会 422、不填目的反而建得成、建完还读不出来"。`Meeting` 响应体已加 `purpose` 并列入 `required`。
- **`patient_no` 筛选会放宽可见范围。** 不带筛选时只返回"我发起的 + 邀请我的"；带 `patient_no` 时返回该患者的会诊（受 T09 科室范围约束，跨科室返回空页）。这是必须的：T32 第 3 条把报告**归档到患者档案**，同科室但没参与会诊的同事要能在"会诊记录"Tab 里读回来——如果按参与人过滤，这个 Tab 对**它服务的人**恰好是空的。

> 报告用 **Jinja2 渲染 HTML + 浏览器打印成 PDF**（`@media print` 适配 A4），不做服务端 PDF 库。
> 报告内容含**各位专家意见 + 结论**，生成后**归档到患者档案**（患者详情"会诊记录"Tab 可见）。
> **这个 Tab 的取数路径是 `GET /api/meetings?patient_no=…`**（按患者过滤），再逐条读 `/api/meetings/{id}/report`。少了 `patient_no` 过滤，报告生成了也没有按患者取回的入口，T32 S1 的最后一步就走不完。

**⚠️ 自动建授权——这是流程 2 的设计亮点，不能漏（T30 第 2 条）**

发起会诊时，后端**自动为每位受邀专家创建一条 `temp_grant`**，有效期 = **预计会诊时间 + 24h 缓冲**。

演示链路：`dr_wang` 发起会诊 → `temp_grant` 表出现 grantee=`dr_chen`、patient=`P20260001`、expire≈24h 后 → `dr_chen` **立刻可跨科室查看该患者**（原本是 404）→ 会诊结束回收 → 到期后刷新**回落 404**。

**会诊资料共享（T31）——四个容易漏的点**

1. 资料存 `uploads/meeting/`，**类型比图片宽**：PDF / 图片 / 文档（不只是 jpg/png/webp）。
2. **仅该会诊的参与者可查看与下载**，权限校验在**服务端**——复制 URL 用非参与医生账号打开必须 **403**，靠前端隐藏不算数。
3. 上传走**与 T26 完全相同的上传组件**（大小上限 + 文件名重命名 + 按内容类型校验 + 审计钩子都共用），T31 第 4 条明令"**不重复实现**"——两套安全检查迟早会漂移。
   ⚠️ **但白名单不同，这里比图片宽。** T31 第 1 条写的是"PDF / 图片 / 文档"，S1 直接传一个 **`.pdf`**；T26 的白名单（`jpg / png / webp`）会把它拒掉。**"共用组件"不等于"共用白名单"**——把 T26 的白名单照抄过来，S1 当场跑不通。契约里 `POST /api/meetings/{id}/materials` 已按"组件共用、类型更宽"写明。
4. **中文文件名不能乱码**（下载 `心电图-2026-09-01.pdf` 要能正常打开），这是 T31 S1 直接验的。下载响应必须带 `Content-Disposition`（含 RFC 5987 的 `filename*`），否则浏览器拿 URL 里的数字 id 当文件名，中文名**根本传不到客户端**——这条判不了就只能算"没做"。

上传/下载动作写审计。

---

### 2.7 M6 患者健康管理

> 任务 T33 归 **D**；T34/T37 归 **C**；T35/T36 归 **B**。🔴 P0（T34）

#### 健康计划

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/health-plans` | 计划列表（按 `patient_no` 筛选）+ 分页 | T35 |
| POST | `/api/health-plans` | 创建个性化方案（用药 / 复诊 / 饮食运动建议 + 起止日期与目标） | T35 |
| GET | `/api/health-plans/{id}` | 详情，含**方案条目与执行状态** | T35 |
| PATCH | `/api/health-plans/{id}` | 修改，含**状态变更**（进行中 / 已完成 / 已终止） | T35 |

- 方案可**关联提醒规则**——创建方案时可一并配置提醒，保存后出现在 T36 的规则列表里（T35 第 3 条）。
- 状态变更写审计。方案受数据范围约束（`dr_wang` 看不到神经内科患者的方案 → 404）。
- 起止日期填反（结束早于开始）→ **422 并指明字段**。

#### 体征数据

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/vitals` | 体征记录列表，支持 `sign_type` + 时间区间 | T33 |
| POST | `/api/patients/{patient_no}/vitals` | 录入体征 | T33 |
| GET | `/api/patients/{patient_no}/vitals/trend` | **趋势图数据**，见下 | T34 |

**`GET /vitals/trend` query**：`sign_type`（**`bp` / `gl` / `hr`**）、`from`、`to`

> ⚠️ **参数名是 `sign_type`，取值只有 3 种。** 初稿写的 `type` 与 `glucose`/`heart_rate`/`weight` 都不对——T33 第 1 条原文是"`sign_type` 至少含 `bp`（血压）/ `gl`（血糖）/ `hr`（心率）"，**没有体重**。

**响应 `data`**

```json
{
  "sign_type": "bp",
  "unit": "mmHg",
  "threshold": { "min": 90, "max": 140, "min_secondary": 60, "max_secondary": 90 },
  "points": [
    {
      "recorded_at": "2026-09-01T08:00:00Z",
      "value": 160, "value_secondary": 100, "is_abnormal": true,
      "threshold": { "min": 90, "max": 140, "min_secondary": 60, "max_secondary": 90 }
    },
    {
      "recorded_at": "2026-09-02T08:00:00Z",
      "value": 128, "value_secondary": 82, "is_abnormal": false,
      "threshold": { "min": 90, "max": 140, "min_secondary": 60, "max_secondary": 90 }
    }
  ]
}
```

> 逐点 `threshold` 带**第二值**，不是只有上下限：T34 场景 S1 悬停血压点要显示
> 「160/100 mmHg（超出阈值 140/90）」。只有 `min`/`max` 的话 tooltip 只能显示 140、
> 显示不出 90。顶层 band 和逐点块**都**带 `*_secondary`。

- **字段名是 `is_abnormal`，不是 `out_of_range`**（T33 第 3 条）。**由后端算**，前端只负责把 `true` 的点标红。
- **血压是双值**（收缩压/舒张压）：`value` + `value_secondary`，前端画两条线或一组上下限（T34 第 6 条）。
- 一个区间内无数据 → `points: []`，前端展示空态提示（**不是白屏、不是报错**）。
- 返回结构是**时间序对，可直接喂 ECharts**，不是原始表行（T33 第 4 条）。

**表结构**（T33 第 1 条）：`vital_sign(id, patient_id, sign_type, value, recorded_at, source)`；`source` 区分 `manual` / `mock`（给模拟数据脚本留的口）。阈值配置**集中管理**，不散落在业务代码中。

#### 提醒

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/reminder-rules` | 提醒规则列表 | T36 |
| POST | `/api/reminder-rules` | 创建规则（`rtype`：用药/复诊/打卡；`cron_expr`） | T36 |
| PATCH | `/api/reminder-rules/{id}` | 修改（含 `active` 启用/停用）。**请求体字段全部可选**，`{"active": false}` 单独一个字段就是合法请求 | T36 |
| GET | `/api/reminders` | 提醒触发记录 | T36 |
| GET | `/api/reminders/unread-count` | **未读数**（工作台红点用） | T36 |
| POST | `/api/reminders/{id}/done` | 标记已执行 | T36 |

**规则字段**（T36 第 1 条）：`rtype`（`medication`/`followup`/`checkin`）、`cron_expr`、`active`。

- 医生工作台显示**未读提醒红点**，进入提醒列表后红点消除——所以需要一个 unread-count 接口，前端不必拉全表自己数。
- 规则**停用后不再生成新提醒**，已有记录保留。
- ⚠️ **停用必须能只发 `active` 一个字段。** T36 第 4 条和场景 S2 都是"把规则设为停用"这**一个**动作。初稿让 PATCH 复用创建用的 schema（`patient_no`/`rtype`/`title`/`cron_expr` 全必填），于是 `{"active": false}` 直接 **422**——停用这个动作根本发不出去。契约现已拆出独立的 `ReminderRuleUpdateRequest`（无必填字段）。
- **方案里勾选的提醒规则可以随方案一起建。** T35 第 3 条要"创建方案时可一并配置提醒"，`POST /api/health-plans` 的 `new_reminder_rules` 接内联规则定义（`reminder_rule_ids` 只接已存在的规则 id）。新建的规则会带上 `health_plan_id` 回指该方案，否则 `ReminderRule.health_plan_id` 在 API 上永远写不进去。
- 提醒生成必须有**幂等键（如 `rule_id + due_at`）**，服务重启不得重复补发（T36 第 5 条）。
- APScheduler 任务**随应用启动注册一次**，不重复注册（多 worker 场景需说明）。

> ✂️ **短信/微信推送已砍**，提醒只落库、只在站内展示。

#### 定期评估

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/assessments` | 评估历史（按时间倒序） | T37 |
| POST | `/api/patients/{patient_no}/assessments` | 新建评估 | T37 |
| GET | `/api/assessments/{id}` | 详情 | T37 |
| PATCH | `/api/assessments/{id}` | 修改（**受限**，见下） | T37 |

**评估字段**（T37 第 1 条）：**周期、评估结论、方案调整建议**（`period` / `conclusion` / `plan_adjustment`），另关联患者与评估医生。

- 评估记录**保存后不可随意修改**（T37 第 3 条）——如需修改至少记录修改时间，所以 `PATCH` 存在但受限。
- **改他人的评估 → 403**（T37 S2：`dr_wang` 改 `dr_li` 创建的评估）。
- 不填结论直接保存 → 前端拦截**且后端也返回 422**（双保险）。
- 评估动作写审计。

---

### 2.8 M8 操作日志与审计

> 任务 T11 归 **B**；T12 归 **C**。🟡 P1
>
> ⚠️ **本模块仅 `admin` 可访问，`senior` 也不行。** T12 验收标准第 3 条原文："非 `admin` 既看不到菜单项、接口也返回 403（双保险，不能只靠隐藏菜单）"。T08 的权限矩阵同样写"审计查询（**仅 admin**）"。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/audit-logs` | **仅 `admin`** | 用户/时间/操作类型三条件组合 + 分页，默认按时间倒序 | T12 |
| GET | `/api/audit-logs/{id}` | **仅 `admin`** | 详情（含 `detail` 原文） | T12 |
| GET | `/api/audit-logs/export` | **仅 `admin`** | 导出 CSV（`text/csv`，不是 JSON） | T12 |

**CSV 导出的三条硬要求**（T12 验收标准第 2 条，容易漏）：

1. 导出内容**与当前筛选条件一致**，不是导出全表
2. 文件名**含时间范围**
3. 必须带 **UTF-8 BOM**，否则 Excel 打开中文乱码

另外列表行要能**展开查看 `detail` 原文**（第 5 条），所以列表接口也得返回 `detail`，不能只在详情接口给。

**性能要求**：单表 ≥1000 条时查询 < 2s，需要给 `user_id`、`created_at`、`action` 建索引。

**query 参数**：`user_id`、`action`、`object_type`、`from`、`to`、`page`、`size`

**单条结构**

```json
{
  "id": 1024,
  "user_id": 2,
  "username": "dr_li",
  "action": "patient.view",
  "object_type": "patient",
  "object_id": "P20260001",
  "ip": "127.0.0.1",
  "method": "GET",
  "path": "/api/patients/P20260001",
  "result": "success",
  "detail": { "…": "…" },
  "created_at": "2026-09-11T02:30:00Z"
}
```

> `audit_logs` 是 **append-only**：没有任何 UPDATE/DELETE 接口，数据库账号本身也不应有这两个权限。
> **写操作**由中间件自动记录，业务代码**不需要**手写（T11 第 1 条）。
> ⚠️ 但**敏感读操作必须业务代码手动埋点**（T11 第 2 条）：患者详情查看、病历详情查看、审计日志导出。中间件只看得到 HTTP 方法和路径，**看不到"这次 GET 读的是谁的数据"**，所以这三类读**不会**被自动记上。T11 场景 S1 直接验的就是"`dr_wang` 查看 `P20260001` 详情 → 新增一条 `patient.view`（含 `object_id`）"——只做中间件的话这条**永远不出现**，T11 S1 和 T12 S1（筛选 `patient.view` 导出）会一起挂。
> 日志写入失败**吞掉并告警，不得阻断主业务**（T11 第 3 条：Redis/日志库不可用时创建患者仍要成功、不得 500）。

---

## 3. 前端页面 ↔ 接口对照

> ⚠️ **"归属"列按 `project_plan.md` 与签收标准的原文填写，不是按"谁写页面"填的。**
> 这两份文档把多个**前端页面**记在了后端同学名下（如 T27 的聊天室 UI 记 B、T32 的列表/详情前端记 D）。
> 下表照实反映，不要自行改判。

| 前端页面 | 主要接口 | 归属（按计划原文） | 现状 |
|---|---|---|---|
| `LoginView`（登录 + 验证码） | `/auth/login` → `/auth/send-code` → `/auth/verify-code` | **C**（T07） | 待建 🔴 |
| `PatientListView` | `GET /patients`、`/departments`、`/patient-groups` | **C**（T15） | ✅ 已接后端（仅列表） |
| `PatientDetailView` | `GET /patients/{no}`、`/histories`、`/allergies`、`/groups` | **C**（T16） | 假数据 |
| `MedicalRecordView`（EMR 编辑器） | `/emr/templates`、`/emr/records`、`PATCH /records/{id}` | **C**（T22）🔴 | 假数据 |
| `OrdersPanel`（医嘱 + 校验弹窗） | `/emr/orders`、`POST /emr/orders/validate`、`/drugs` | **C**（T23）🔴 | 假数据 |
| `ReviewQueueView` | `/emr/reviews`、`POST /records/{id}/review` | **A**（T24） | 假数据 |
| `ConsultationsView` | `/consultations`、`WS /ws/chat/{room_id}`、`/uploads/images` | **B**（T25–T27） | 假数据 |
| `RemoteConsultationView` | `/meetings`、`/meetings/{id}/materials`、`/report` | **D**（T30–T32） | 假数据 |
| `HealthManagementView` | `/health-plans`(T35, **B**)、`/patients/{no}/vitals/trend`(T34, **C**)、`/reminders/unread-count`(T36, **B**) | **B + C** | 假数据 |
| `MySubmissionsView`（我的提交 + 退回意见） | `GET /emr/my-submissions` | **A**（T24） | 未建 |
| `AuditLogView` | `GET /audit-logs`、`/audit-logs/export` | **C**（T12） | 假数据 |
| 用户管理页 | `/users`、`/roles` | **无任务、无 owner** ⚠️ | 未建 |
| 临时授权管理页 | `/temp-grants` | **无任务、无 owner** ⚠️ | 未建 |

### 3.1 这次核对暴露的问题

我原先在 §2 各模块下写的"负责人 C 前端"是**我推断的，不是文档写的**，已按原文改正。改完之后的实际情况是：

- **C 在计划里带前端交付的任务共 9 项**：T07、T12、T15、T16、T17（前后端各半）、T22、T23、T34、T37。
- **M3 问诊和 M5 会诊的前端页面不在 C 名下**，分别记在 B 和 D。
- 但**用户管理页和临时授权管理页在全部 44 个任务里找不到归属**——功能上有 `/users`、`/temp-grants` 两组接口，却没有任何任务说谁做这两个页面。（44 = `project_plan.md` §5 的 37 个 T + 7 个 M。初稿写 43，是漏数了一个。）

前两点是 C 需要澄清的（否则评审时容易被问"问诊页面为什么没做"），第三点是团队需要在 Day 6 晨会摊派的。

---

## 4. 需要改造的现有实现

按 2026-09-11 决议"都按签收标准改"，以下现有代码需要跟上：

| 项 | 现状 | 目标 | 影响面 |
|---|---|---|---|
| 响应结构 | `{"data": …}` / `{"error":{"message":…}}` | `{code, message, data}` | `main.py` 异常处理器 + `schemas.py` + 前端 `client.js` + README + AGENTS.md |
| 角色名 | `administrator`/`doctor`/`department_manager` | `admin`/`senior`/`junior` | `seed.py` + 迁移 + 前端权限判断 |
| 患者标识 | 整数 `id` | 字符串 `patient_no`（`P20260001`） | `models.py` + 迁移 + 所有患者路由 + 前端 |
| 分页参数 | `offset`/`limit` | `page`/`size`，返回 `{items,total,page,size}` | `main.py` + 前端 |
| 患者编辑 | **无 PATCH 接口** | `PATCH /api/patients/{patient_no}` | 新增 |
| 删除鉴权 | `DELETE /api/patients/{id}` 无认证 | 需登录 + 角色 | 新增 |

> 前四项是**破坏性改动**：改了以后现有前端页面会挂。**执行顺序建议**：先后端改 + 前端 `client.js` 一次性跟上，同一个 PR 里做完，避免中间态。
> 这件事和 T15 的验收项直接相关：*"Mock 数据结构与 Swagger 契约字段级一致，切换到真接口只改开关/baseURL，不改组件代码。"*

---

## 5. 未决问题（需要有人拍板）

| # | 问题 | 谁来定 | 阻塞谁 |
|---|---|---|---|
| 1 | **M03 接口文档整理是 F 的任务**——本文档与 F 的工作重叠，需要和 F 对齐分工 | 团队 | 下周评审 |
| 2 | 用户管理页 / 临时授权页**没有任务、没有 owner**（§3） | 团队 | Sprint 2 |
| 3 | `/api/users` CRUD 本身也没有明确任务，只是被 T08 列为受保护资源（§2.2） | B | Sprint 1 |
| 4 | 本文档是否入库？入库意味着 README/AGENTS.md 里"响应约定"两行也要同步改 | 团队 | — |
| 5 | C 的负荷超载与 T17 是否转给 D（**签收标准 §2.2** 推荐方案①；超 17h 可用量约 1.5–3h，`project_plan.md` §4.3 记作 "1.5 over"） | Day 6 晨会 | Sprint 2 |
| 6 | **M3/M5 的前端页面记在 B 和 D 名下**，但这几个页面目前是 C 做的假数据版；需要明确谁继续维护（§3.1） | 团队 | Sprint 2 |

> 初稿的第 2 条（"`approve` 之后是直接 `archived` 还是中间多一个 `approved`"）**已由 T24 拍板删除**：T24 第 2 条明确"**通过 → 归档**"，没有中间态。

---

## 6. 本文档的核对记录

### 第三轮核对（2026-09-11，逐任务全量）

前两轮是抽点和按模块核；这一轮改成**把签收标准的 46 个条目（T01–T37 + M01–M07）逐条对着契约的 104 个操作走一遍**，不看任何一方的自我描述，只比对原文。查出的都是**签收标准明确要求、而契约没做到**的缺口——即"照着契约写代码，某个签收场景当场跑不通"。

| 缺口 | 签收标准要求 | 契约原文 |
|---|---|---|
| 敏感读埋点被否定 | T11 §2：患者详情/病历详情/审计导出**手动埋点** | 写着业务代码"**never** writes an audit entry by hand"——中间件看不见 GET 读了谁的数据，T11 S1 / T12 S1 一起挂 |
| 退回后无法重提 | T24 §3：`rejected` 改完**重新提交**（版本 +1） | submit 的 400 文案："不在 `draft` 就无处可进" |
| 缺剂量拿不到 422 | T20 S2：未填剂量 → **422 且指明字段** | `dose` 是可选的 |
| 漏一条审计动作 | T20 S2：审计可见 **create** / modify / stop | `medical_order.create` 全文 0 次 |
| 提醒停用发不出去 | T36 §4 / S2：把规则设为**停用** | PATCH 复用创建 schema，`{"active": false}` → **422** |
| 会诊目的是死字段 | T30 §2 三个入参含**目的**；§4 详情要**显示目的** | 目的映射到**可选**的 `description`，且响应体里没有该字段——照 T30 发文会 422、不填反而建得成、建完还读不出来 |
| 会诊记录 Tab 读不到 | T32 §3：报告**归档到患者档案**，"会诊记录"Tab 可见 | 列表写"我发起的 + 邀请我的"，同一段又说 `patient_no` 供"没发起也没参加"的人读——自相矛盾；报告读接口也是参与者限定 |
| 信令房间不设防 | T29 §5：**非参与者无法接入信令房间** | WS 只声明 `101/401/404`，无 403、无参与者校验，却在别处声称"与 T25 信令房间同一条规则" |
| T31 S1 的 PDF 被拒 | T31 §1 / S1：上传 **PDF** | 写成"类型白名单与 T26 同一套" → 只剩 jpg/png/webp |
| 中文文件名传不回来 | T31 §3 / S1：下载**中文名不乱码** | 下载响应没有 `Content-Disposition`，浏览器只会拿 URL 里的数字 id 当文件名 |
| 工作台少一个字段 | T27 §1：列表显示患者名、**最后一条消息**、时间 | `Consultation` 没有该字段 |
| tooltip 少半边阈值 | T34 S1：悬停显示"160/100（超出阈值 **140/90**）" | 逐点 `threshold` 只有 `min`/`max`，没有第二值 |
| 方案建规则不可表达 | T35 §3：创建方案时**一并配置提醒** | `reminder_rule_ids` 只收已有 id；`health_plan_id` 全文 1 次（定义处），API 写不进去 |
| 评估没有日期校验 | T37 §5：**日期校验齐全** | 评估表没有任何日期规则 |

**契约内部自洽性问题**（没有对应的签收条目，但自己打自己）：

- PATCH 病历写"`version` is incremented"，而 submit 同一份文件写 v1(draft) → v2(pending) → v3。T19 S1 的三步算术要求 **PATCH 不产生版本**，已改。
- `/api/consultations/{id}/accept` 错状态用 400、"别人先接了"用 409；会诊模块统一用 409。
- `PATCH /api/health-plans/{id}` 复用创建用的全必填 schema。
- 13 个列表接口返回扁平数组，与此处"所有列表接口统一分页"不符（已知，故意不改）。
- 图片白名单只写了 jpg/png，**漏 `webp`**（T26 与签收标准都写了三种）。
- `GET /api/departments` 是唯一没有任务标注的接口——它**确实**不属于任何任务（标为"已有"），已在契约里写明这一点，而不是编一个任务号。

**一条是签收标准自己写错的**：T08 §4 把匿名白名单写成"仅含 `login` / `verify-code` / `health`"，**漏了 `send-code`**——而发验证码逻辑上不可能要求先登录。契约把它列进 `security: []` 是对的，**这条要改的是签收标准，不是契约**。

### 第二轮核对（2026-09-11，契约级）

对全文（含 `openapi.yaml`）逐条回原文重核了一遍，重点查"字段名/状态码/状态机"这类**会直接导致后端写错**的出入。结果：

| 出错的表述 | 原文实际是怎么写的 |
|---|---|
| 健康检查"任一不可用则返回 **503**" | T03 §1：**恒返回 200**，Redis 断连只标 `redis:"down"`，**不得 500** |
| JWT payload 与用户对象用 `role` | T05 §3：字段名是 **`title`** |
| 归档病历修改返回 **400** | T19 §3 / T24 §4：**409** |
| `temp_grant` 用 `target_type` / `target_id` / `duration_hours` / `expires_at` / `status` | T10 §1：表是 `temp_grant(grantee_id, patient_id, reason, expire_at, is_valid)` |
| 签发临时授权仅 `senior` | T10 §1：**`admin` / `senior` 都可以** |
| `temp_grant` 到期后访问"403" | T10 §3：**回落为 404** |
| 模块模板支持 6 种 `type`（含 `checkbox`） | T18 §1：**只有 5 种**，无 `checkbox` |
| `approve` "或 `approved` 再由归档步骤处理" | T24 §2：**通过即 `archived`，无中间态** |
| 体征参数叫 `type`，取值 `glucose`/`heart_rate`/`weight` | T33 §1：是 **`sign_type`**，取值 **`bp`/`gl`/`hr`**（无 `weight`） |
| 超阈值字段 `out_of_range` | T33 §3：**`is_abnormal`** |
| 会诊状态机含 `archived` | T30 §1：止于 `completed`，另含 **`declined`** 分支 |
| 发起会诊限 `senior` | T30 S1：**`dr_wang`（junior）发起** |
| 发起会诊不建授权 | T30 §2：**自动为每位专家建 `temp_grant`**（= 会诊时间 + 24h） |
| WebSocket 路径 `/ws/consultations/{id}` | T25 §1：**`/ws/chat/{room_id}`**，问诊与会诊复用 |
| 患者新建表单可填 `patient_no` | T13 §1：**系统生成且唯一** |
| 搜索参数 `q` 模糊匹配"患者编号" | T13 §2：`patient_no` 是**精确**匹配，且四条件可 AND |
| `message` 一律不给用户看 | T23 §5（例外）：医嘱校验文案**必须与后端一致、原样展示** |
| M3/M5 相关：上传无约束、无 `my-submissions`、无未读数、无评估 PATCH | 分别来自 T26 §2、T24 §3、T36 §2、T37 §3 |

**与"提交状态"无关的、纯文档层面的更正**：§7 的砍掉清单已按 M01 第 2 条重写（见下）。

### 第一轮核对（2026-09-11，归属级）

本文档的"归属"列在 2026-09-11 按 `project_plan.md` 与 `医生工作平台-任务链路图与签收标准.md` 逐条核对过，**两份文档的任务归属完全一致**。

核对中改正了初稿的以下错误，记录在此以免再犯：

| 初稿写的 | 实际的 |
|---|---|
| 基建 T03 归 A | T03 归 **B** |
| M3 问诊"B 后端 + C 前端" | **M3 无 C 任务**，T25/T26/T27=B、T28=D、T29=A |
| M5 会诊"D 后端 + C 前端" | **M5 无 C 任务**，T30/T31/T32 全归 D |
| M6"D 后端 + C 前端" | T33=D、T34/T37=C、T35/T36=**B** |
| 健康计划接口标 T33 | 归 **T35**（B） |
| "越权一律 403，不区分存在性" | **两套口径**：角色权限不足→403；跨科室→**404**（T08 S2 / T09） |
| 审计日志"`admin`/`senior` 可访问" | **仅 `admin`**，`senior` 也返回 403（T12 验收第 3 条） |

---

## 7. 已砍的老师需求（答辩时要能解释）

**M01 第 2 条要求规格书"明确写出 6 条去除项及答辩口径"，且 M01 S2 要求口径与《计划》3.2 节完全一致。** 所以下面是**权威的六条**，答辩时按这个数：

| # | 需求 | 原因 | 替代 |
|---|---|---|---|
| 1 | **医生社区**（M7 同行社交） | 范围裁剪 | — |
| 2 | **会话自动录像** / 云端存储 | 收费 | 只记录通话元数据（时长、起止） |
| 3 | **短信验证码** | 需企业资质 + 费用 | 邮箱验证码（免费） |
| 4 | **人脸识别** | 需活体检测服务 | 密码 + 邮箱验证码 2FA |
| 5 | **IoT 体征采集** | 无硬件 | 医生手工录入 + 模拟脚本 |
| 6 | **企业级监控面板**（Prometheus 等） | 范围裁剪 | 现有 `/api/health` + 审计日志 |

**这六条之外的技术选型决策**（也是答辩会问到的，但不计入"六条去除项"）：

| 项 | 原因 | 替代 |
|---|---|---|
| 腾讯云 TRTC 视频 | 需账号/实名/费用 | 浏览器原生 **WebRTC 点对点** + WebSocket 信令 |
| MinIO 对象存储 | 范围裁剪 | 本地磁盘 `uploads/` + StaticFiles |
| 微服务拆分 | 范围裁剪 | 模块化单体 |
| 动态 RBAC 配置界面 | 范围裁剪 | 角色在代码/种子数据中固定 |
| 服务端 PDF 库 | 省依赖 | Jinja2 渲染 HTML + 浏览器打印 |
| **患者端 App** | 明确不做 | 医生工作台为唯一前端 |

---

*本文档由 C 起草，2026-09-11。字段级细节以 `openapi.yaml` 为准，冲突时先改本文再改 YAML。*

### M1 通行密钥扩展（T05 / T07）

- `POST /api/auth/passkeys/register/options`：登录后创建注册挑战。
- `POST /api/auth/passkeys/register/verify`：验证设备响应并绑定当前账号。
- `POST /api/auth/passkeys/login/options`：创建无用户名登录挑战。
- `POST /api/auth/passkeys/login/verify`：验证签名并返回现有 TokenResponse。

挑战有效期 300 秒且只能使用一次，必须通过设备用户验证。账号、角色和科室仍由后端管理；不收集人脸图像。请求和响应以 openapi.yaml 为准。
