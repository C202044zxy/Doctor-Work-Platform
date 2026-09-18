# 医生工作平台 · API 接口索引

> 版本 v2.0 ｜ 2026-09-14
> 机器可读契约见同目录 [`openapi.yaml`](openapi.yaml)。
> 本文档是**接口清单 + 中文说明**，供后端同学按模块实现；`openapi.yaml` 是精确的字段级契约。

**权威层级**（本文档**不是**最高权威，也不与其它文档争夺口径）

| 口径 | 权威文档 |
|---|---|
| 任务 / 模块编号、负责人、状态、排期、技术与部署选型 | `docs/01-任务安排.md` |
| 测试场景、演示基线、模拟红线 | `docs/02-测试场景.md` |
| 字段级契约（字段名 / 类型 / 状态码 / 枚举） | `docs/api/openapi.yaml`；**本文档是它的索引与说明** |

本文与上述文档冲突时，以上述文档为准；本文与 `openapi.yaml` 冲突时以 `openapi.yaml` 为准，并在同一个 PR 内把本文补齐。

---

## 0. 这份文档怎么用

- **后端同学**：找到你负责的任务 ID（见每节的"任务"列，编号体系见 `docs/01-任务安排.md`），按表格里的路径和请求/响应体实现。字段类型以 `openapi.yaml` 为准。
- **前端同学**：`openapi.yaml` 可以直接喂给 mock 工具生成假数据；页面与接口的对照见 [§3](#3-前端页面--接口对照)。
- **契约变更**：`openapi.yaml` 与本文档必须在**同一个 PR 内**同步修改（见 `docs/01-任务安排.md` §6）。

**标记约定**

| 标记 | 含义 |
|---|---|
| 🔴 P0 | 本模块的 P0 交付项；不通过则该模块**整体不予签收** |
| 🟡 P1 | 应有功能 |
| ⚪ P2 | 可裁剪；全项目唯一可整体砍掉的缓冲 |
| ✂️ | 老师原始需求中**已明确砍掉**，不在本期范围（当前仅 M7 医生社区） |
| 🧪 | 以**模拟实现**纳入本期范围；必须带"模拟"标识，答辩按 `docs/02-测试场景.md` §5 的诚实口径说明 |

---

## 1. 全局约定

### 1.1 前缀

所有业务接口以 `/api` 开头。两处例外：健康检查的 `/health` 别名（与 `/api/health` 同函数，见 §2.1），以及 S5 的 `GET /metrics`（Prometheus 文本格式，见 §1.2）。

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
- `message` 默认是**给开发者看的英文短句**，前端不直接展示给用户，只用于排查；前端展示自己的英文文案。（界面全英文，见 `docs/01-任务安排.md` §8.5。）
- **一处例外**：医嘱校验的 `messages[]`（见 §2.4）**必须原样展示给用户**。M4-06 要求"弹窗文案与后端返回的校验详情一致，不另写一套文案"——即弹窗里的"该患者对【青霉素类】过敏，禁止开立"就是后端那句话，前端不得改写。这是**唯一**允许前端直出 `message` 的地方。
- `data` 失败时为 `null`，前端可以无条件读 `res.data.data`。
- 这是**服务端强制**的：由全局异常处理器统一包装，路由函数只管返回裸数据。
- **两处例外**（不要据此认为信封是普适的）：
  - `/api/health/ready`：信封之外额外返回顶层 `status` 与 `checks`（`checks` 与 `data` 内容相同）；依赖不可用时返回 **503**，见 §1.6 与 §2.1。`/api/health/live` 同样多返回一个顶层 `status`。
  - `GET /metrics`：返回 Prometheus 文本格式（`text/plain; version=0.0.4`），**不做任何信封包装**——包成 `{code,message,data}` 就没有任何 Prometheus 工具能解析它。

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
- **三种 401 的 `message` 必须可区分**（M1-01）：无 token / token 过期 / token 在黑名单。前端据此给不同提示（登出后立即重放同一 JWT 必须 401，见场景 M1-T5）。
- `status = disabled` 的用户即使持有**有效 token** 也被拒绝（同样是 401）。
- **登录失败限速**：同一账号连续 5 次密码错误必须被锁定/限流，不得无限重试（M1-01 / M1-08，场景 M1-T6）。

### 1.5 角色与数据范围

**功能权限**（角色决定"能做什么"）

| 角色代码 | 含义 | 说明 |
|---|---|---|
| `admin` | 管理员 | 用户管理、模板维护、全部数据、审计日志、临时授权 |
| `senior` | 主任医师 | 病历审阅/归档、临时授权、本科室数据 |
| `junior` | 住院医师 | 写病历、开医嘱，**看不到**审阅队列/审计日志/用户管理 |

> 后端 `seed.py` 已按上面三个代码落库（`admin` / `senior` / `junior`）；旧值 `administrator` / `doctor` / `department_manager` 已作废，不得再出现在种子数据、接口或前端中。
>
> ⚠️ **JWT payload 里的字段名是 `title`，不是 `role`**（M1-01：payload 含 `user_id` / `title` / `department` / `jti`）。前端读当前角色要读 `user.title`。接口返回的用户对象同样用 `title`。

**数据权限**（科室决定"能看谁"）

- 医生只能看到**自己科室**的患者、病历、问诊、会诊。
- `admin` 不受科室限制。
- `temp_grant`（临时授权）是唯一的限时例外：**`admin` / `senior` 可发起**（M1-06），为一个具体**患者**授予跨科室访问，到期自动失效，访问回落为 404。
- 过滤逻辑必须在 **service 层统一入口**实现，不是每个路由各写一遍（M1-05，代码评审项）。

**权限失败分两种口径，不要混用**（M1-04 / M1-05）：

| 情形 | 返回 | 理由 |
|---|---|---|
| **角色功能权限不足**：该角色根本不能做这个动作（如 `junior` 调审阅接口） | **403**，`message` 指明缺少的权限 | 动作本身对该角色不可见，不涉及数据 |
| **数据范围外**：动作允许，但对象属于别的科室 | **404**，与"真的不存在"完全同口径 | 不泄露"该患者存在"这一事实 |

场景 M1-T4 直接验这条：`dr_wang`（junior）调 `GET /api/patients/P20260003`（Neurology 患者）**必须返回 404，返回 403 即不签收**。

所以"返回 404 还是 403"取决于**是角色不够还是科室不够**，不是"越权一律 403"。

### 1.6 错误码

| code | 场景 |
|---|---|
| 0 | 成功 |
| 401 | 未登录 / token 过期 / 已在黑名单（三者 `message` 可区分）；`status=disabled` |
| 403 | 角色不具备该功能权限（如 `junior` 调审阅接口、非参与人下载会诊资料或接入会诊信令房间） |
| 404 | 资源不存在，**或超出本科室数据范围**（两者同口径，不区分） |
| 409 | **归档锁定**（对 `archived` 病历的任何修改，M4-02 / M4-07）、乐观锁版本不一致、重复加入分组、**医嘱过敏拦截**（M4-04）、**会诊状态机非法跳转**（M5-01） |
| 422 | 参数校验失败，`message` **指出具体字段名** |
| 429 | 验证码发送过于频繁（**响应含剩余秒数**）、登录密码连续错误锁定 |
| 500 | 未捕获异常 |
| 503 | **已配置的依赖不可用**：`/api/health/ready` 探到依赖为 `down`（`message="Dependencies unavailable"`）、Redis 不可达（`message="Redis unavailable"`）、数据库不可达（`message="Database unavailable"`）、`JWT_SECRET` 未配置或短于 32 字符、SMTP 未配置或未启用 TLS |

**⚠️ 三条容易搞错的**：

1. **归档锁定是 409，不是 400。** M4-02 与 M4-07 都是 409（"任何修改接口对归档病历返回 409 并提示'已归档，不可修改'"）。
2. **`/health` 与 `/api/health` 永远返回 200，永不 5xx。** 这一对是**进程存活路由**：Redis 断连时**仍返回 200** 且标识 `redis:"down"`，**不得 500 崩溃**；依赖挂了不改变状态码，只在 body 里体现（M0-03）。这样负载均衡与 CI 探针不会因为 Redis 抖动把整个应用判死。
3. **但 `/api/health/ready` 不同，它确实会返回 503。** 它是**就绪探针**：`available = "down" not in checks.values()`，为假时 `status_code = 503`、`code = 503`、`message = "Dependencies unavailable"`。**不要把第 2 条套到 `/api/health/ready` 上**——两者语义正好相反，这正是本表存在 503 的原因。（`/api/health/live` 恒 200。）

`409` 与 `422` 在医嘱拦截上**两者都被接受**（M4-04 的完成标准写"返回 422/409"）；本契约统一取 **409**，理由是"拦截是状态冲突而非参数格式错误"。

### 1.7 枚举值（前后端必须一致）

| 字段 | 取值 | 出处 |
|---|---|---|
| `title`（**不是 `role`**） | `admin` / `senior` / `junior` | M1-01 |
| `gender` | `male` / `female` / `unknown` | — |
| `allergy.allergy_type` | `drug` / `food` / `other` | M2-02 |
| `allergy.severity` | `mild` / `moderate` / `severe` | M2-02 |
| `record.status` | `draft` / `pending` / `rejected` / `archived` | M4-02 |
| `emr_field.type` | `text` / `number` / `date` / `select` / `textarea` | M4-01 |
| `order.order_type` | `drug` / `lab` / `exam` | M4-03 |
| `order.status` | `active` / `stopped` | M4-03 |
| `order.validation_status` | `passed` / `warning` / `blocked` | M4-03 |
| `order.validation_detail[].kind` | `allergy` / `dose` | M4-04 |
| `consultation.status` | `waiting` / `active` / `ended` | M3-03 |
| `message.sender_type` | `doctor` / `patient_assist` | M3-02 |
| `meeting.status` | `requested` / `accepted` / `declined` / `in_progress` / `completed` | M5-01 |
| `meeting.participants[].status` | `invited` / `accepted` / `declined` | M5-01 |
| `vital.sign_type` | `bp` / `gl` / `hr` | M6-01 |
| `vital.source` | `manual` / `mock` | M6-01 |
| `reminder.rtype` | `medication` / `followup` / `checkin` | M6-04 |
| `health_plan.status` | `active` / `completed` / `terminated` | M6-03 |
| `health_plan.entries[].kind` | `medication` / `followup` / `diet_exercise` | M6-03 |
| `meeting_report.status` | `draft` / `final` | M5-03 |
| `review.decision` | `approve` / `reject` | M4-02 |
| `user.status` | `active` / `disabled` | M1-01 |
| `audit_log.result` | `success` / `failure` | M8-01 |

> ⚠️ **`vital.source` 以 `openapi.yaml` 的 `VitalSource` 为准，当前只有 `manual` / `mock`。** S4（IoT 体征采集模拟）落地时需扩为 **`manual` / `mock` / `device`**；届时 `openapi.yaml`、本文档与前端类型必须**在同一个 PR 内**同步（见 `docs/01-任务安排.md` §4.1 与 S4-01）。**在 `openapi.yaml` 改之前，`device` 不是合法取值。**

**改动说明**（相对早期草稿）：

- `role` → `title`（M1-01）。
- `vital.type` 的 `glucose`/`heart_rate`/`weight` → `gl`/`hr`，**`weight` 不在范围内**（M6-01 只要求 bp/gl/hr）。
- `meeting.status` 补 `declined`，并**去掉草稿多写的 `archived`**（M5-01 状态机止于 `completed`）。
- 模板字段类型去掉 `checkbox`（M4-01 只列 5 种）。
- `order.status` **去掉 `modified`**：M4-03 的停用是软停用（`status` → `stopped`，行保留），改单并不改变状态，它记在审计里，不是第三态。
- `order.validation_detail[].kind` **去掉 `duplicate`**：M4-04 的三级检查只有"过敏命中"和"剂量超范围"两种会触发，其余是 `passed` 且 `reasons` 为空，没有第三种。
- 其余 7 组在此**补录**（它们一直在契约里，只是早前本表漏列，导致 §1.7 与实际枚举对不上）。

### 1.8 时间与脱敏

- 时间统一 **ISO 8601 UTC**，例如 `2026-09-11T02:30:00Z`。前端负责转本地时区展示。
- 手机号、身份证等敏感字段：列表接口返回**脱敏后**的值（`138****1234`）；详情接口按角色决定是否返回明文。字段名带 `_enc` 表示库中加密存储。

---

## 2. 接口清单

### 2.1 基建

> 任务 M0-03。🔴 P0

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/health` | **恒返回 200**，body 为 `{code:0, data:{db, redis}}` | M0-03 |
| GET | `/health` | 上面那条的**同函数别名**（同一 handler），响应逐字节相同；场景 M9-T2 比对的就是这两个路径 | M0-03 |
| GET | `/api/health/live` | 存活探针，**恒 200**；响应为正常信封 + 一个冗余的顶层 `status` | 已有 |
| GET | `/api/health/ready` | 就绪探针；**依赖为 `down` 时返回 503**（`code=503`、`message="Dependencies unavailable"`），响应另含顶层 `status` 与 `checks` | 已有 |

**关键约束：`/health` 与 `/api/health` 永远返回 200，永不 5xx。** M0-03 原文——

> `GET /health` 返回 `{code:0, data:{db:"ok", redis:"ok"}}`；**Redis 断连时仍返回 200 且标识 `redis:"down"`，不得 500 崩溃**。

`db` / `redis` 各取 `ok` / `down` / `disabled`（`disabled` = 该依赖未配置 URL）。**依赖挂掉只改 body，不改状态码**——这样负载均衡与 CI 探针不会因为 Redis 抖动把整个应用判死。

> ⚠️ **这条只适用于 `/health` 与 `/api/health`。** `/api/health/ready` 的语义**正好相反**：依赖不健康就返回 **503**，状态码随依赖状态改变。两者并存时不要把探针当签收对象，也不要以为 `/api/health/ready` 会永远 200。详见 §1.6。

**路径别名（已定）**

场景 M9-T2 比对的是 `GET /health`（不带 `/api`）与 `GET /api/health`；仓库约定是"所有路由在 `/api` 下"（`README.md`、`AGENTS.md`）。两边都保留：`/api/health` 为主路由，`/health` 注册同函数的别名，**响应必须完全一致**。别名不是可选项——只挂 `/api/health` 会让 M9-T2 判不过。

> **已知契约偏差（待 M0-05 处理）**：`/api/health/live` 与 `/api/health/ready` **已实现**，且 CI 的 `smoke.py` 依赖它们，但**这两条路径目前不在 `docs/api/openapi.yaml` 里**。这是"实现有、契约无"的缺口；M0-05 的契约校验脚本上线后，这类偏差必须能被 CI 拦截。本文与 `openapi.yaml` 的一致性由 M0-05 负责，**不要在本文里单方面补字段**。

---

### 2.2 M1 安全账户登录

> 任务 M1-01 / M1-02 / M1-04 / M1-05 / M1-06。🔴 P0

#### 认证流程

| 方法 | 路径 | 🔒 | 角色 | 说明 | 任务 |
|---|---|---|---|---|---|
| POST | `/api/auth/login` | — | — | 提交 `username` + `password`，校验通过返回一次性 `ticket`（5 分钟）；密码错误 401，**连续 5 次锁定** | M1-01 |
| POST | `/api/auth/send-code` | — | — | 用 `ticket` 换发邮箱验证码；**60 秒内限一次**、单账号单日上限 20 次，超限 429 且**响应带剩余等待秒数** | M1-02 |
| POST | `/api/auth/verify-code` | — | — | 提交 `ticket` + `code`，成功返回 `access_token` 与用户信息；错误 401 | M1-01 |
| POST | `/api/auth/logout` | 🔒 | 任意 | `jti` 进 Redis 黑名单，立即失效 | M1-01 |
| GET | `/api/me` | 🔒 | 任意 | 当前用户信息：`id` / `username` / `name` / **`title`** / `department` | M1-01 |

**验证码的四条硬约束**（M1-02，容易漏）：6 位数字、Redis **TTL = 300s**、**一次性**（用过即废，二次提交失败）、**绝不出现在任何响应体与日志中**。SMTP 不可用时必须返回明确错误、**不吞异常**。

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
    "department": "Cardiology"
  }
}
```

#### 用户管理（仅 `admin`）

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/users` | `admin` | 列表，支持 `q`（姓名/账号）、**`title`**、`department` 筛选 + 分页 | M1-07 |
| POST | `/api/users` | `admin` | 创建用户（`username`/`password`/`name`/`email`/`title`/`department` 均必填） | M1-07 |
| GET | `/api/users/{id}` | `admin` | 详情 | M1-07 |
| PATCH | `/api/users/{id}` | `admin` | 改 **`title`** / `department` / `status` / `name`（全选填） | M1-07 |
| GET | `/api/roles` | 🔒 任意 | 角色字典（返回三个角色代码与显示名） | M1-07 |
| GET | `/api/departments` | 🔒 任意 | 科室字典（**已有**）。**契约里唯一不挂任务 ID 的接口**——它先于任务表存在，也没有任何测试场景约束它，所以不编任务号，契约中直接写明这一点 | 已有 |

> ℹ️ 这组 `/api/users` CRUD 与前端用户管理页归属 **M1-07**（`docs/01-任务安排.md` §3.2、§7.3）。
> 注意 `department` 的取值只有 `Information Technology` / `Cardiology` / `Neurology` 三个，**顺序即 id 1 / 2 / 3，不得调换**（测试按下标取值）。

#### 临时授权 temp_grant

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/temp-grants` | `admin`/`senior` | 列表 | M1-06 |
| POST | `/api/temp-grants` | **`admin`/`senior`** | 发起授权 | M1-06 |
| DELETE | `/api/temp-grants/{id}` | `admin`/`senior` | 手动立即失效（演示"权限收回"；M5-01 会诊结束时调用） | M1-06 |

**表结构（M1-06 原文照抄）：`temp_grant(grantee_id, patient_id, reason, expire_at, is_valid)`**

没有 `target_type`、没有 `target_id`、没有 `duration_hours`、没有 `expires_at`（是 `expire_at`），也没有 `status` 枚举——**有效期只由 `expire_at` 表示，有效性只由 `is_valid` 布尔表示**。

> ⚠️ 上表里 M1-06 写的 `patient_id` 是**库表内部键**；接口层一律用患者的业务键 `patient_no`（`P20260001`），请求与响应里都不会出现 `patient_id`。同理 `medical_order` 与 `vital_sign` 的表结构注释里也是 `patient_id`，接口字段是 `patient_no`——两者不是同一个东西，不要照抄表结构当接口字段名。

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
- **`expire_at` 由调用方给定，不是后端用时长算出来的。** M5-01 自动建授权时也是后端直接算出"预计会诊时间 + 24h 缓冲"填进来。

> 演示要点：授权到期后该用户访问目标患者必须**回落到 404**（不是 403），不需要重启服务。APScheduler 每分钟扫描 `expire_at < now() AND is_valid = 1` → 置 `is_valid = 0`。
> 审计记录两条：`temp_grant.create` 与 `temp_grant.expire`。任务**随应用启动注册一次**，不重复注册。

---

### 2.3 M2 患者信息管理

> 任务 M2-01 / M2-02 / M2-03 / M2-04 / M2-05。🟡 P1

#### 患者

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients` | 列表 + 多条件搜索 + 分页，见下 | M2-01 |
| POST | `/api/patients` | 新建。**`patient_no` 由系统生成且唯一，请求体不接受该字段** | M2-01 |
| GET | `/api/patients/{patient_no}` | 详情（含过敏史、分组） | M2-02 |
| PATCH | `/api/patients/{patient_no}` | 编辑基础信息 | M2-01 |
| DELETE | `/api/patients/{patient_no}` | 删除。**删除策略（软删/级联）须写进接口文档** | M2-01 |

> `patient_no` 系统生成（M2-01），格式如 `P20260001`。前端**不能在新建表单里填患者号**——这是早期草稿漏掉的一处契约差异（场景 M2-T4 验"传入 `patient_no` 被忽略而非写入"）。

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

> **四个搜索条件必须可任意 AND 组合**（M2-01）：姓名模糊、`patient_no` 精确、`symptom_tags` 匹配、入院日期区间。四条件全空 → 返回全量分页（场景 M2-T1）。
> 默认按 `created_at` 倒序（M2-01）。

**`GET /api/patients` 单条 `items[]` 结构**

```json
{
  "patient_no": "P20260001",
  "name": "赵大勇",
  "gender": "male",
  "birth_date": "1968-03-12",
  "phone_masked": "138****1234",
  "department": "Cardiology",
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
| GET | `/api/patients/{patient_no}/histories` | 病史列表（时间线用，按 `onset_date` 倒序） | M2-06 |
| POST | `/api/patients/{patient_no}/histories` | 新增 | M2-06 |
| PATCH | `/api/histories/{id}` | 修改 | M2-06 |
| DELETE | `/api/histories/{id}` | 删除 | M2-06 |

#### 过敏史

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/allergies` | 过敏列表 | M2-02 |
| POST | `/api/patients/{patient_no}/allergies` | 新增 | M2-02 |
| PATCH | `/api/allergies/{id}` | 修改 | M2-02 |
| DELETE | `/api/allergies/{id}` | 删除 | M2-02 |
| GET | `/api/allergens` | 过敏原字典（至少覆盖：**青霉素类、磺胺类、头孢类、阿司匹林、造影剂**，支持自定义补充） | M2-02 |

**过敏记录字段**（M2-02）：`allergen`、`allergy_type`、`severity`、`recorded_at`。

- 过敏**增/删/改均写审计**（`allergy.delete` 等，记被删过敏原名称；场景 M2-T8）。
- 删除患者时过敏记录的**级联策略要明确**（M2-02）。
- 详情接口返回的这份过敏列表**同时供前端警示条和 M4-04 校验引擎消费**——同一数据源，不许各查各的（M2-02）。后端需提供标准函数 `get_patient_allergens(patient_no)`。

#### 患者分组

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patient-groups` | 分组列表（含每组人数） | M2-05 |
| POST | `/api/patient-groups` | 创建分组（按病种 / 管理状态） | M2-05 |
| PATCH | `/api/patient-groups/{id}` | 重命名 | M2-05 |
| DELETE | `/api/patient-groups/{id}` | 删除 | M2-05 |
| POST | `/api/patient-groups/{id}/members` | 批量加入，体 `{"patient_nos": ["P20260001"]}` | M2-05 |
| DELETE | `/api/patient-groups/{id}/members` | 批量移出，同上 | M2-05 |

---

### 2.4 M4 电子病历 ⭐（最高分模块）

> 任务 M4-01 / M4-02 / M4-03 / M4-04 / M4-05 / M4-06 / M4-07。🔴 P0

#### 病历模板

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/templates` | 🔒 任意 | 模板列表 | M4-01 |
| POST | `/api/emr/templates` | `admin` | 新建模板 | M4-01 |
| GET | `/api/emr/templates/{id}` | 🔒 任意 | 详情，**含 `fields_json`** | M4-01 |
| PATCH | `/api/emr/templates/{id}` | `admin` | 修改 | M4-01 |

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

支持的 `type`：**`text` / `number` / `date` / `select` / `textarea` —— 只有这 5 种**（M4-01）。不做通用表单引擎。

> ⚠️ 早期草稿把 `checkbox` 也列了进去，**本契约没有这一种**（场景 M4-T1 验"字段 ≥ 6，控件类型正确"）。

**其他要点**
- 表结构 `emr_template(id, name, fields_json, is_active)`；**停用走 `is_active`**，不是删除。
- 需**2 个预置模板**：「入院记录」「日常病程记录」，字段数各 ≥ 6。
- 模板**停用后不影响已有病历**——历史病历按当时模板渲染（M4-01）。
- 仅 `admin` 可维护；变更写审计 `emr_template.*`。

#### 病历

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/records` | 🔒 | 列表，支持 `patient_no` / `status` / `author_id` 筛选 + 分页 | M4-02 |
| POST | `/api/emr/records` | `senior`/`junior` | 新建草稿 | M4-02 |
| GET | `/api/emr/records/{id}` | 🔒 | 详情，含 `content_json`、`status`、`version` | M4-02 |
| PATCH | `/api/emr/records/{id}` | 作者 | 保存草稿，**带 `version` 做乐观锁** | M4-05 |
| POST | `/api/emr/records/{id}/submit` | 作者 | 提交审阅：`draft` → `pending` | M4-02 |
| GET | `/api/emr/records/{id}/versions` | 🔒 | 版本历史 | M4-02 |
| POST | `/api/emr/records/{id}/amend` | **作者** | 对**已归档**病历追加补记（不修改原文）。**不是 `senior` 专属**——场景 M4-T5 里补记的人正是 `dr_wang`（junior） | M4-02 |

**`PATCH` 请求体**

```json
{ "content_json": { "chief_complaint": "…" }, "version": 3 }
```

- `version` 不匹配返回 **409**，前端提示"病历已被他人修改，请刷新"。
- 目标病历 `status = archived` 时返回 **409**（归档锁定，只读）——**不是 400**。两个 409 用 `message` 区分。
- 版本号每次提交 **+1 并存全量快照**（不是只存差异）；可查历史版本列表并按版本号查看内容。
- 病历内容按模板 `fields_json` 校验，必填项缺失 → **422 且指出字段名**。
- 归档后的修订只能走**「补记」**（新增关联版本，原版本内容不变），不能改原文。
- **保存失败不得丢失用户已输入内容**——这是 M4-05 的 P0 验收项，前端要保留草稿（本地暂存；场景 M4-T15）。

#### 医嘱

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/emr/orders` | 按 `record_id` 查医嘱列表 | M4-03 |
| POST | `/api/emr/orders` | 开立医嘱（**保存前必须过校验**，见下） | M4-03 |
| PATCH | `/api/emr/orders/{id}` | 修改 | M4-03 |
| POST | `/api/emr/orders/{id}/stop` | 停止医嘱 | M4-03 |
| POST | `/api/emr/orders/validate` | **只校验不保存**，供前端实时预检 | M4-04 |
| GET | `/api/drugs` | 药品字典（含 `contraindications` 过敏原标签） | M4-04 |

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

- **两类校验可同时命中，并按严重度排序展示**（M4-04，六格矩阵第 5 格）；校验规则**配置化**，不硬编码在业务代码里。
- **红色弹窗绝不能有强制开立的出口**——这是 M4-06 的 P0 验收项，也是答辩卖点。校验必须在**服务端**再做一遍，绕过前端直接调 API 仍被拦截（场景 M4-T7）。
- 🟡 警告的文案要**带常规范围**（"常规剂量 20–40mg/日，当前 80mg"），🔴 拦截的文案要**带过敏原名**（"该患者对【青霉素类】过敏，禁止开立"）。
- **这两种文案前端原样展示，不要自己改写**（M4-06），见 §1.2 的例外说明。
- 每条医嘱落库时留存 `validation_status` 与**校验详情**（命中了哪条规则），并写审计。
- **开立 / 改单 / 停用三个动作各写一条审计**，动作名分别是 `medical_order.create` / `medical_order.modify` / `medical_order.stop`。场景 M4-T10 的要求是"查审计日志可见 **create / modify / stop 三条记录**"——**早期草稿只写了 modify 和 stop，漏了 `create`**，照它生成代码的话 M4-T10 只能查到两条。
- **药品项缺 `dose` → 422 并指明字段**（场景 M4-T9："未填写剂量 → 422 且指明字段"）。契约没有把 `dose` 写成全局必填，因为 `lab`/`exam` 项本来就没有剂量；规则是**按 `order_type` 条件生效**：`drug` 项必须有 `dose`，其余不受这条约束。

#### 审阅与归档

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/emr/reviews` | `senior` | 待审队列（`status = pending`，按提交时间排序） | M4-07 |
| POST | `/api/emr/records/{id}/review` | `senior` | 审阅：`{"action":"approve"\|"reject","comment":"…"}` | M4-07 |
| GET | `/api/emr/my-submissions` | 🔒 作者本人 | "我的提交"：作者查看自己的病历及**退回意见** | M4-07 |
| POST | `/api/emr/records/{id}/archive` | `senior` | 归档 → 只读 | M4-07 |

- **`approve` 之后直接 `archived`，中间没有 `approved` 状态。** M4-07 原文："**通过 → 归档**：状态置 `archived`，写入 `reviewer_id` / `reviewed_at`，病历转为只读。"（早期草稿的"或 `approved` 再由归档步骤处理"是多余的，已删除；场景 M4-T11。）
- `reject` 必须带 `comment` → `status` → `rejected` 并保存 `review_comment`；作者在"我的提交"里能看到该意见，修改后**重新提交（版本 +1，重新进 `pending`）**（场景 M4-T13）。
- **归档后任何修改接口一律 409**，这是 M4-07 的 P0 验收项（前端编辑器同时置只读态，双保险；场景 M4-T4）。
- 审阅动作（通过/退回）写审计，含审阅人、时间、意见。
- `junior` **看不到待审列表**（RBAC），但**能看自己的"我的提交"**——这是两个不同的列表，别合并成一个。

---

### 2.5 M3 在线问诊

> 任务 M3-01 / M3-02 / M3-03 / M3-04 / M3-05。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/consultations` | 🔒 | 列表，按 `status` 分组（`waiting`/`active`/`ended`）+ 分页；每条带 `last_message` / `last_message_at`（工作台列表要显示"最后一条消息"） | M3-03 |
| POST | `/api/consultations` | `junior`/`senior` | 接诊/发起 | M3-03 |
| GET | `/api/consultations/{id}` | 🔒 | 详情 | M3-03 |
| POST | `/api/consultations/{id}/accept` | 🔒 | 接诊：`waiting` → `active` | M3-03 |
| POST | `/api/consultations/{id}/end` | 🔒 | 结束：`active` → `ended` | M3-03 |
| GET | `/api/consultations/{id}/messages` | 🔒 | 历史消息（分页，倒序） | M3-02 |
| POST | `/api/consultations/{id}/messages` | 🔒 | 发消息（**HTTP 兜底**，正常走 WebSocket） | M3-02 |
| GET | `/api/consultations/records` | 🔒 | 检索历史问诊（按患者/日期/关键词） | M3-04 |
| GET | `/api/consultations/export` | 🔒 | 导出 CSV | M3-04 |
| POST | `/api/uploads/images` | 🔒 | 上传图片，`multipart/form-data`，返回 `{"url":"/uploads/…"}` | M3-02 |
| GET | `/api/consultations/{id}/calls` | 参与人 | 通话记录列表（分页、倒序）；**"可在问诊记录中查看"就靠这条**（M3-05） | M3-05 |
| POST | `/api/consultations/{id}/calls` | 参与人 | 记录一次通话的元数据（发起/接通/结束时间、时长）。**通话结束后才写**，非参与人 403 | M3-05 |
| WS | **`/ws/chat/{room_id}`** | 🔒 | 实时图文消息（房间 = `consultation_id` 或 `meeting_id`） | M3-01 |

**上传图片的四条硬约束**（M3-02，安全项，容易被跳过）：

1. 类型白名单 **jpg / png / webp**，且按**内容类型**校验（改扩展名的 `.exe` 必须被拒）
2. 大小上限 **≤ 5MB**
3. **文件名重命名为随机值**——防覆盖与路径穿越（上传 `../evil.png` 后不得逃逸出 `uploads/`）
4. `uploads/` 目录不进 Git，且有定期清理策略说明

> ⚠️ **WebSocket 路径是 `/ws/chat/{room_id}`，不是 `/ws/consultations/{id}`。** M3-01 原文写的是 `WebSocket 路由（如 /ws/chat/{room_id}）`；且房间号可以是 `consultation_id` **或 `meeting_id`**——所以路径里是通用的 `room_id`，问诊和会诊**复用同一个路由**，不各开一条。
> 连接时**校验 JWT，无效 token 拒绝握手**。异常断开要清理在线状态（不残留"幽灵在线"）。

**WebSocket 消息信封**

```json
{ "type": "message", "data": { "id": 1024, "sender_type": "doctor", "content": "…", "image_url": null, "sent_at": "…" } }
```

`type` 取值：`message` / `typing` / `joined` / `left` / `call_offer` / `call_answer` / `ice_candidate`。

> **广播的 `data` 必须带持久化后的 `id`。** M3-03 要求聊天气泡有"**发送中/已送达**"两态：客户端先乐观渲染一条"发送中"的气泡，收到带同一个 `id` 的回显后才把它置为"已送达"。没有 `id` 就没法把回显和本地气泡对上，这个状态机做不出来。

> **信令房间要校验参与者。** M3-05 要求"**非参与者无法接入信令房间**"——只有该会话的参与医生能发起/接听。握手里 JWT 有效但不在会话名单上的人，应在升级完成前拿到 **403**（场景 M3-T2）。只写 `/calls` 的 403 不够：信令走的是 WS，得在 WS 上也挡住。

> WebRTC 信令复用同一个 WebSocket 房间（最后三个 `type`），**不单独开信令服务**。
> 🧪 云端录像、自动录像以**模拟**纳入本期（S3 会话录像模拟）：回放重建的是通话**事件时间线**，**不产生任何音视频文件**，页面须有"模拟回放 · 无音视频"横幅。`/calls` 仍只记录元数据（时长、起止）。**不得描述为"已实现录像"**，口径见 `docs/02-测试场景.md` §5。

---

### 2.6 M5 远程会诊

> 任务 M5-01 / M5-02 / M5-03。

**状态机**：`requested` → `accepted` → `in_progress` → `completed`，另有 `declined` 分支（M5-01）

> ⚠️ **没有 `archived` 状态。** 被归档的是**报告**（落到患者档案），不是会诊本身（M5-03）。早期草稿多写了 `archived`。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/meetings` | 🔒 | 列表（我发起的 + 邀请我的），按 `status` / **`patient_no`** 筛选 | M5-01 |
| POST | `/api/meetings` | **`junior`/`senior`** | 发起会诊：选患者 + 选专家（可多选）+ 填**目的**（`purpose`，**必填**）；`scheduled_at` **可选**（不填则由后端取当前时刻）；`title` 可选（不填由 `purpose` 派生） | M5-01 |
| GET | `/api/meetings/{id}` | 参与人 | 详情 | M5-01 |
| POST | `/api/meetings/{id}/accept` | 被邀者 | 接受邀请：`requested` → `accepted` | M5-01 |
| POST | `/api/meetings/{id}/decline` | 被邀者 | 拒绝邀请：`requested` → `declined` | M5-01 |
| POST | `/api/meetings/{id}/start` | 发起人 | `accepted` → `in_progress` | M5-01 |
| POST | `/api/meetings/{id}/complete` | 发起人 | `in_progress` → `completed` | M5-01 |
| GET | `/api/meetings/{id}/participants` | 参与人 | 参与人列表及接受状态 | M5-01 |
| GET | `/api/meetings/{id}/materials` | 参与人 | 资料列表 | M5-02 |
| POST | `/api/meetings/{id}/materials` | 参与人 | 上传病历/影像（`multipart`） | M5-02 |
| GET | `/api/materials/{id}/download` | 参与人 | 下载资料 | M5-02 |
| GET | `/api/meetings/{id}/report` | 参与人 **或**能触达该患者的同科室医生 | 会诊报告（归档后从患者档案可读） | M5-03 |
| POST | `/api/meetings/{id}/report` | **参与人** | 生成/保存报告（场景 M5-T5 要让非参与医生拿 403） | M5-03 |
| GET | `/api/meetings/{id}/report/print` | 参与人 | 返回可打印的 HTML（Jinja2 渲染） | M5-03 |
| GET | `/api/meetings/doctors` | 🔒 | **契约之外**：专家候选目录（`id/username/name/title/department`，**不含邮箱**）。契约里 `/api/users` 是管理员专属，喂不了 `junior` 发起的专家选择框；M1-07 落地后删除 | M5-01 |

- **实现状态（2026-09-17）**：上表 11 条契约路径 + 1 条契约外新增（`/api/meetings/doctors`）全部落地于 `backend/app/meetings.py`，`backend/tests/test_meetings.py` **17 个用例通过**；前端 `/remote-consultation` 与患者详情「会诊记录」Tab 已接真实接口。
- **发起人可以是 `junior`。** 场景 M5-T1 的原文就是"**`dr_wang` 对 `P20260001` 发起会诊邀请 `dr_chen`**"，而 `dr_wang` 是 junior。早期草稿把发起限死为 `senior`，**会让流程 2 的演示跑不起来**。
- **状态机非法跳转返回 409**（如 `requested` 直接跳 `completed`；场景 M5-T3）。
- 非受邀人访问该会诊 → 403/404，不泄露存在性。
- 会诊发起/接受/状态变更均写审计。
- **`scheduled_at` 不是必填。** M5-01 列的入参只有"患者 + 专家 + 目的"，所以前端不传时间也必须能发起；不传时后端按当前时刻落库。它唯一的额外作用是为每位受邀专家算 `temp_grant` 的有效期（该时刻 + 24h）。
- **"目的"是必填的 `purpose`，不是可选的 `description`。** M5-01 把目的列为三个入参之一，又要求详情把它显示出来——所以它必须既**必填**又**能读回**（场景 M5-T3 验缺 `purpose` → 422 且指明字段）。早期草稿把它写成可选的 `description` 且响应体里根本没有这个字段，结果是"照着三项入参发文会 422、不填目的反而建得成、建完还读不出来"。`Meeting` 响应体已加 `purpose` 并列入 `required`。
- **`patient_no` 筛选会放宽可见范围。** 不带筛选时只返回"我发起的 + 邀请我的"；带 `patient_no` 时返回该患者的会诊（受 M1-05 科室范围约束，跨科室返回空页）。这是必须的：M5-03 把报告**归档到患者档案**，同科室但没参与会诊的同事要能在"会诊记录"Tab 里读回来——如果按参与人过滤，这个 Tab 对**它服务的人**恰好是空的（场景 M5-T7）。

> 报告用 **Jinja2 渲染 HTML + 浏览器打印成 PDF**（`@media print` 适配 A4），不做服务端 PDF 库。
> 报告内容含**各位专家意见 + 结论**，生成后**归档到患者档案**（患者详情"会诊记录"Tab 可见）。
> **这个 Tab 的取数路径是 `GET /api/meetings?patient_no=…`**（按患者过滤），再逐条读 `/api/meetings/{id}/report`。少了 `patient_no` 过滤，报告生成了也没有按患者取回的入口，流程 2 的最后一步就走不完。

**⚠️ 自动建授权——这是流程 2 的设计亮点，不能漏（M5-01）**

发起会诊时，后端**自动为每位受邀专家创建一条 `temp_grant`**，有效期 = **预计会诊时间 + 24h 缓冲**。

演示链路：`dr_wang` 发起会诊 → `temp_grant` 表出现 grantee=`dr_chen`、patient=`P20260001`、expire≈24h 后 → `dr_chen` **立刻可跨科室查看该患者**（原本是 404）→ 会诊结束回收 → 到期后刷新**回落 404**。

**会诊资料共享（M5-02）——四个容易漏的点**

1. 资料存 `uploads/meeting/`，**类型比图片宽**：PDF / 图片 / 文档（不只是 jpg/png/webp）。
2. **仅该会诊的参与者可查看与下载**，权限校验在**服务端**——复制 URL 用非参与医生账号打开必须 **403**，靠前端隐藏不算数（场景 M5-T5）。
3. 上传走**与 M3-02 完全相同的上传组件**（大小上限 + 文件名重命名 + 按内容类型校验 + 审计钩子都共用），M5-02 明令"**不重复实现**"——两套安全检查迟早会漂移。
   ⚠️ **但白名单不同，这里比图片宽。** M5-02 要求的是"PDF / 图片 / 文档"，场景 M5-T4 直接传一个 **`.pdf`**；M3-02 的白名单（`jpg / png / webp`）会把它拒掉。**"共用组件"不等于"共用白名单"**——把 M3-02 的白名单照抄过来，M5-T4 当场跑不通。契约里 `POST /api/meetings/{id}/materials` 已按"组件共用、类型更宽"写明。
4. **中文文件名不能乱码**（下载 `心电图-2026-09-01.pdf` 要能正常打开），这是场景 M5-T4 直接验的。下载响应必须带 `Content-Disposition`（含 RFC 5987 的 `filename*`），否则浏览器拿 URL 里的数字 id 当文件名，中文名**根本传不到客户端**——这条判不了就只能算"没做"。

上传/下载动作写审计。

---

### 2.7 M6 患者健康管理

> 任务 M6-01 / M6-02 / M6-03 / M6-04 / M6-05。🔴 P0（M6-02）

#### 健康计划

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/health-plans` | 计划列表（按 `patient_no` 筛选）+ 分页 | M6-03 |
| POST | `/api/health-plans` | 创建个性化方案（用药 / 复诊 / 饮食运动建议 + 起止日期与目标） | M6-03 |
| GET | `/api/health-plans/{id}` | 详情，含**方案条目与执行状态** | M6-03 |
| PATCH | `/api/health-plans/{id}` | 修改，含**状态变更**（进行中 / 已完成 / 已终止） | M6-03 |

- 方案可**关联提醒规则**——创建方案时可一并配置提醒，保存后出现在 M6-04 的规则列表里（M6-03；场景 M6-T8）。
- 状态变更写审计。方案受数据范围约束（`dr_wang` 看不到 Neurology 患者的方案 → 404；场景 M6-T9）。
- 起止日期填反（结束早于开始）→ **422 并指明字段**（场景 M6-T9）。

#### 体征数据

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/vitals` | 体征记录列表，支持 `sign_type` + 时间区间 | M6-01 |
| POST | `/api/patients/{patient_no}/vitals` | 录入体征 | M6-01 |
| GET | `/api/patients/{patient_no}/vitals/trend` | **趋势图数据**，见下 | M6-02 |

**`GET /vitals/trend` query**：`sign_type`（**`bp` / `gl` / `hr`**）、`from`、`to`

> ⚠️ **参数名是 `sign_type`，取值只有 3 种。** 早期草稿写的 `type` 与 `glucose`/`heart_rate`/`weight` 都不对——M6-01 原文是"`sign_type` 至少含 `bp`（血压）/ `gl`（血糖）/ `hr`（心率）"，**没有体重**。

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

> 逐点 `threshold` 带**第二值**，不是只有上下限：场景 M6-T4 悬停血压点要显示
> 「160/100 mmHg（超出阈值 140/90）」。只有 `min`/`max` 的话 tooltip 只能显示 140、
> 显示不出 90。顶层 band 和逐点块**都**带 `*_secondary`。

- **字段名是 `is_abnormal`，不是 `out_of_range`**（M6-01）。**由后端算**，前端只负责把 `true` 的点标红。
- **血压是双值**（收缩压/舒张压）：`value` + `value_secondary`，前端画两条线或一组上下限（M6-02）。
- 一个区间内无数据 → `points: []`，前端展示空态提示（**不是白屏、不是报错**；场景 M6-T5）。
- 返回结构是**时间序对，可直接喂 ECharts**，不是原始表行（M6-01）。

**表结构**（M6-01）：`vital_sign(id, patient_id, sign_type, value, recorded_at, source)`；`source` 区分 `manual` / `mock`（给模拟数据脚本留的口）。S4 落地后会增加 `device`（见 §1.7 的说明）。阈值配置**集中管理**，不散落在业务代码中。

#### 提醒

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/reminder-rules` | 提醒规则列表 | M6-04 |
| POST | `/api/reminder-rules` | 创建规则（`rtype`：用药/复诊/打卡；`cron_expr`） | M6-04 |
| PATCH | `/api/reminder-rules/{id}` | 修改（含 `active` 启用/停用）。**请求体字段全部可选**，`{"active": false}` 单独一个字段就是合法请求 | M6-04 |
| GET | `/api/reminders` | 提醒触发记录 | M6-04 |
| GET | `/api/reminders/unread-count` | **未读数**（工作台红点用） | M6-04 |
| POST | `/api/reminders/{id}/done` | 标记已执行 | M6-04 |

**规则字段**（M6-04）：`rtype`（`medication`/`followup`/`checkin`）、`cron_expr`、`active`。

- 医生工作台显示**未读提醒红点**，进入提醒列表后红点消除——所以需要一个 unread-count 接口，前端不必拉全表自己数（场景 M6-T6）。
- 规则**停用后不再生成新提醒**，已有记录保留。
- ⚠️ **停用必须能只发 `active` 一个字段。** M6-04 与场景 M6-T7 都是"把规则设为停用"这**一个**动作。早期草稿让 PATCH 复用创建用的 schema（`patient_no`/`rtype`/`title`/`cron_expr` 全必填），于是 `{"active": false}` 直接 **422**——停用这个动作根本发不出去。契约现已拆出独立的 `ReminderRuleUpdateRequest`（无必填字段）。
- **方案里勾选的提醒规则可以随方案一起建。** M6-03 要"创建方案时可一并配置提醒"，`POST /api/health-plans` 的 `new_reminder_rules` 接内联规则定义（`reminder_rule_ids` 只接已存在的规则 id）。新建的规则会带上 `health_plan_id` 回指该方案，否则 `ReminderRule.health_plan_id` 在 API 上永远写不进去。
- 提醒生成必须有**幂等键（如 `rule_id + due_at`）**，服务重启不得重复补发（M6-04；场景 M6-T7）。
- APScheduler 任务**随应用启动注册一次**，不重复注册（多 worker 场景需说明）。

> 🧪 **短信/微信推送以模拟纳入本期（S1 短信验证模拟）**：验证码本身是真实的（Redis 签发、TTL、一次性、与邮箱共用同一限流计数器），但**消息不出网、不接运营商**，只写入本地 `notify_outbox`；页面须有"短信（模拟）"标识。**不得描述为"已实现短信发送"**，口径见 `docs/02-测试场景.md` §5。

#### 定期评估

| 方法 | 路径 | 说明 | 任务 |
|---|---|---|---|
| GET | `/api/patients/{patient_no}/assessments` | 评估历史（按时间倒序） | M6-05 |
| POST | `/api/patients/{patient_no}/assessments` | 新建评估 | M6-05 |
| GET | `/api/assessments/{id}` | 详情 | M6-05 |
| PATCH | `/api/assessments/{id}` | 修改（**受限**，见下） | M6-05 |

**评估字段**（M6-05）：**周期、评估结论、方案调整建议**（`period` / `conclusion` / `plan_adjustment`），另关联患者与评估医生。

- 评估记录**保存后不可随意修改**（M6-05）——如需修改至少记录修改时间，所以 `PATCH` 存在但受限。
- **改他人的评估 → 403**（场景 M6-T11：`dr_wang` 改 `dr_li` 创建的评估）。
- 不填结论直接保存 → 前端拦截**且后端也返回 422**（双保险）。
- 评估动作写审计。

---

### 2.8 M8 操作日志与审计

> 任务 M8-01 / M8-02。🟡 P1
>
> ⚠️ **本模块仅 `admin` 可访问，`senior` 也不行。** M8-02 原文："非 `admin` 既看不到菜单项、接口也返回 403（双保险，不能只靠隐藏菜单）"。M1-04 的权限矩阵同样写"审计查询（**仅 admin**）"。场景 M8-T6 验的正是这条。

| 方法 | 路径 | 角色 | 说明 | 任务 |
|---|---|---|---|---|
| GET | `/api/audit-logs` | **仅 `admin`** | 用户/时间/操作类型三条件组合 + 分页，默认按时间倒序 | M8-02 |
| GET | `/api/audit-logs/{id}` | **仅 `admin`** | 详情（含 `detail` 原文） | M8-02 |
| GET | `/api/audit-logs/export` | **仅 `admin`** | 导出 CSV（`text/csv`，不是 JSON） | M8-02 |

**CSV 导出的三条硬要求**（M8-02，容易漏）：

1. 导出内容**与当前筛选条件一致**，不是导出全表
2. 文件名**含时间范围**
3. 必须带 **UTF-8 BOM**，否则 Excel 打开中文乱码

另外列表行要能**展开查看 `detail` 原文**（场景 M8-T8），所以列表接口也得返回 `detail`，不能只在详情接口给。

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
> **写操作**由中间件自动记录，业务代码**不需要**手写（M8-01；场景 M8-T2）。
> ⚠️ 但**敏感读操作必须业务代码手动埋点**（M8-01）：患者详情查看、病历详情查看、审计日志导出。中间件只看得到 HTTP 方法和路径，**看不到"这次 GET 读的是谁的数据"**，所以这三类读**不会**被自动记上。场景 M8-T1 直接验的就是"`dr_wang` 查看 `P20260001` 详情 → 新增一条 `patient.view`（含 `object_id`）"——只做中间件的话这条**永远不出现**，M8-T1 与 M8-T3（筛选 `patient.view` 导出）会一起挂。
> 日志写入失败**吞掉并告警，不得阻断主业务**（M8-01：Redis/日志库不可用时创建患者仍要成功、不得 500；场景 M8-T5）。

---

## 3. 前端页面 ↔ 接口对照

> 本表按 `frontend/src/router/index.js`、`frontend/src/views/`、`frontend/src/api/` 的**代码事实**填写（2026-09-14 核对），**不含负责人/归属列**——任务归属见 `docs/01-任务安排.md`。
> "现状"只有两种取值：**真实接口**（`import ... from '../api/client'`）与 **假数据**（`import ... from '../api/demo-data'`）。

**路由与视图（`frontend/src/router/index.js`）**

| 路由 | 视图 | 消费的接口 | 现状 |
|---|---|---|---|
| `/login` | `LoginView.vue` | `POST /api/auth/login` → `POST /api/auth/send-code` → `POST /api/auth/verify-code`；注册分支 `POST /api/auth/signup` → `POST /api/auth/signup/verify`；人脸分支 `POST /api/auth/face/login` | ✅ **真实接口** |
| `/dashboard` | `DashboardView.vue` | 无（工作台计数、排班、待办全部来自 `demo-data.js`） | ⚠️ **假数据** |
| `/patients` | `PatientListView.vue` | `GET /api/patients`、`POST /api/patients`、`DELETE /api/patients/{patient_no}`、`GET /api/departments` | ✅ **真实接口** |
| `/patients/:patientNo` | `PatientDetailView.vue` | `GET /api/patients/{patient_no}`、`GET /api/meetings?patient_no=…`、`GET /api/meetings/{id}/report`（`?version=` 读历史版本）、`GET /api/meetings/{id}/report/print`（仅参与人）；「Health data」Tab（`components/PatientHealth.vue`，M6）消费 `/api/patients/{no}/vitals`、`/vitals/trend`、`/api/health-plans`、`/api/reminder-rules`、`/api/reminders`、`/unread-count`、`/api/patients/{no}/assessments`、`/api/assessments/{id}` | ✅ **真实接口**（**「会诊记录」Tab** 属 M5、**「Health data」Tab** 属 M6，其余 Tab 属 M2-04） |
| `/records` | `MedicalRecordView.vue` | 计划消费 `/api/emr/templates`、`/api/emr/records`、`PATCH /api/emr/records/{id}`、`/api/drugs`、`POST /api/emr/orders/validate` | ⚠️ **假数据** |
| `/consultations` | `ConsultationsView.vue` | 计划消费 `/api/consultations`、`GET /api/consultations/{id}/messages`、`WS /ws/chat/{room_id}`、`POST /api/uploads/images` | ⚠️ **假数据** |
| `/remote-consultation` | `RemoteConsultationView.vue` | `GET/POST /api/meetings`、`/accept`、`/decline`、`/start`、`/complete`、`/api/meetings/doctors`、`/api/meetings/{id}/materials`、`/api/materials/{id}/download`、`/api/meetings/{id}/report`、`/report/print` | ✅ **真实接口** |
| `/review` | `ReviewQueueView.vue` | 计划消费 `/api/emr/reviews`、`POST /api/emr/records/{id}/review`、`GET /api/emr/my-submissions` | ⚠️ **假数据** |
| `/audit` | `AuditLogView.vue` | `GET /api/audit-logs`（筛选 / 分页）、`GET /api/audit-logs/export`（服务端 CSV） | ✅ **真实接口**（T12） |

**应用外壳（`frontend/src/App.vue` / `frontend/src/session.js`）**

| 位置 | 消费的接口 | 现状 |
|---|---|---|
| 会话恢复（路由守卫） | `GET /api/me` | ✅ **真实接口** |
| 顶栏登出 | `POST /api/auth/logout` | ✅ **真实接口** |
| 侧边栏计数 | `demo-data.js` 的 `counts` | ⚠️ **假数据** |
| 后端可用性探测 | `GET /api/health/ready`（`health.ready()`） | ✅ **真实接口** |

**尚未建立的前端页面**（有接口、有场景，但没有对应的 `.vue` 文件）

| 页面 | 对应任务 | 说明 |
|---|---|---|
| 患者详情页 | M2-04 | `PatientDetailView` 已随 M5 建出**身份头 + 「会诊记录」Tab**；病史 / 分组 / 过敏编辑仍属 M2-04 |
| 用户管理页 | M1-07 | `frontend/src/views/` 下无对应文件 |
| 临时授权管理页 | M1-06 | 同上 |
| 我的提交 | M4-07 | 现由 `ReviewQueueView` 以假数据承担 |
| 医嘱面板 | M4-06 | 现由 `MedicalRecordView` 以假数据承担 |
| 系统监控页 / 设备管理页 / 回放页 / 权限矩阵页 | S5 / S4 / S3 / S6 | 模拟模块，均零代码 |

> **⚠️ 演示红线**：`demo-data.js` 目前被 **4 个 View + `App.vue`** 直接 import（`DashboardView` / `ConsultationsView` / `MedicalRecordView` / `ReviewQueueView` 与外壳的 `counts`）。**在 M9-05 收口前，这些页面上的任何数字都不是真实数据**，不得进入演示路径。`/login`、`/patients`、`/patients/:patientNo`（含 M6 的「Health data」Tab）、`/remote-consultation`、`/audit` 以及外壳的会话/登出/探针走真实接口——`RemoteConsultationView`（M5）、`AuditLogView`（T12）与健康管理面板（M6，原 `/health` 页已于 2026-09-18 并入患者详情）已退出这份名单。

---

## 4. 已砍与已收回的老师需求（答辩时要能解释）

### 4.1 真正砍掉的：只有一条

| # | 需求 | 结论 | 原因 | 答辩口径 |
|---|---|---|---|---|
| 1 | **医生社区（M7）** | **整模块不做**，列为二期，仅保留答辩口径 | 老师原始需求标注 Optional；与核心诊疗流程相对独立；工作量约等于整个问诊模块 | "M7 在原始需求里标注 Optional，与核心诊疗流程独立。为保证核心模块质量整体列为二期；二期设计要点已保留——病例须手动脱敏后发布、与患者库物理隔离、模块可整体关闭。" |

> **只有 M7 是真正砍掉的。** 下面 4.2 的六条**不是砍掉**，而是以"模拟实现"纳入了本期范围。

### 4.2 由"砍掉"改为"模拟实现"的需求（S1–S6）

> 统一口径是"**模拟实现 + 可替换 provider**"：接口、状态机与业务逻辑是真实的，被模拟的只是外部依赖。
> ⚠️ **不得表述为**"已实现短信发送""已实现人脸识别""已实现通话录像""已接入真实设备""已部署 Prometheus / Grafana""已实现企业级 RBAC 后台"。红线细则见 `docs/02-测试场景.md` §5 与 `docs/01-任务安排.md` §4.1。

| 模块 | 原需求 | **属于模拟的部分** | 真实存在的部分 | 界面 / 接口标识 |
|---|---|---|---|---|
| **S1** 短信验证模拟 | 短信验证码 | **消息不出网、不接运营商**；"发送"只是写入本地 `notify_outbox` | 验证码的签发 / TTL / 一次性 / 限流逻辑，与邮箱通道共用同一套（走 Redis） | 登录页标注 **"SMS (simulated)"**；模拟手机浮层标注 **"Simulated message — nothing was sent"**（界面全英文） |
| **S2** 人脸识别模拟 | 人脸识别 + 活体检测 | **不做任何生物特征比对**：`match_face()` 恒返回 `True` | 摄像头采集、图片 SHA-256 指纹存取、不落原图的隐私约束、登录限流 | 人脸模态标注 **"SIMULATION"**；响应体带 `"mock": true`（界面全英文） |
| **S3** 会话录像模拟 | 会话自动录像 / 云端存储 | **不产生任何音视频文件**；回放是通话**事件时间线**的重建 | 通话元数据（起止 / 时长 / 异常标记）来自真实信令与心跳 | 回放页顶部固定"模拟回放 · 无音视频"横幅；打印页同样标注 |
| **S4** IoT 体征采集模拟 | IoT 体征采集 | **没有真机**；数据由 `scripts/device_simulator.py` 按节拍生成 | 上报接口、`device_token` 鉴权、阈值判定、数据范围过滤——与真实设备**完全相同，无演示后门** | 设备页标"模拟设备（无真机）"；模拟器输出打印 "SIMULATED" |
| **S5** 监控面板模拟 | Prometheus + Grafana + 告警 | **不部署 Prometheus / Grafana**；图表自采自绘、告警站内自投 | 指标采集中间件、P95 计算、告警判定；`/metrics` 输出 Prometheus 文本格式，可被真实 Prometheus 抓取 | 监控页标"自采指标（替代 Prometheus / Grafana）" |
| **S6** 动态权限配置模拟 | 动态 RBAC 配置界面 | **只做"角色 × 功能权限"矩阵**；数据权限仍由 `department` + `temp_grant` 决定 | 权限矩阵落库、改动即时生效、变更留痕与一键回滚 | 矩阵页标"功能权限矩阵（数据权限由科室 + 临时授权决定）" |

**⚠️ S2 必须逐字诚实说明（当前实现的事实）：**

> `backend/app/face_login.py` 的 `match_face()` **无条件返回 `True`**，且 `/api/auth/face/login` 在匿名白名单上——**任意一个合法 JPEG 加上一个已存在且启用的用户名，就能换到一枚真实的 2 小时 token**。
> 这**不是人脸识别**，是"用户名存在即通过"的模拟。真实存在的只有摄像头采集、图片指纹存取与"不落原图"的约束。
> **任何文档、PPT、演示脚本都不得把它写成"人脸识别已实现"，也不得声称它能比对生物特征。**

> **另一条待补**：S1 目前**尚未开始**——登录页当前只有**邮箱**与**人脸**两条渠道，短信渠道与"模拟手机"浮层都还不存在。答辩时按未完成记，不写成已完成。

### 4.3 技术选型决策（不计入"去除项"）

| 项 | 原因 | 替代 |
|---|---|---|
| 腾讯云 TRTC 视频 | 需账号/实名/费用 | 浏览器原生 **WebRTC 点对点** + WebSocket 信令 |
| MinIO 对象存储 | 范围裁剪 | 本地磁盘 `uploads/` + StaticFiles |
| 微服务拆分 | 范围裁剪 | 模块化单体 |
| 服务端 PDF 库 | 省依赖 | Jinja2 渲染 HTML + 浏览器打印 |
| **患者端 App（S7）** | 明确不做；仅当主模块与 S1–S6 全部收口且有余量时再评估 | 医生工作台为唯一前端 |

---

### M1 人脸登录

- `POST /api/auth/face/login`：提交 `username` 和 `photo`（base64 JPEG data URL），返回现有 `TokenResponse`。
- `match_face()` **无条件返回 `True`**：任意合法 JPEG + 一个已存在且启用的用户名即可签发 **2 小时 token**。**这不是人脸识别**，见 §4.2 的诚实口径。图片仅在内存中处理，不保存。
- 通行密钥接口已移除。请求和响应以 `openapi.yaml` 为准。

### Email signup extension（M1-01 / M1-02 / M1-04）

- `POST /api/auth/signup`: public; `SignupRequest` sends an email code and returns
  `LoginResponse` (`ticket`, `expires_in: 300`). Existing department name required.
- `POST /api/auth/signup/verify`: public; `VerifyCodeRequest` creates a pending junior
  account and returns `OkData`. Does not issue a session. Administrator activation
  uses `python -m app.activate_user`; subsequent login uses existing email 2FA.
- Validation, duplicates, expired/used tickets, code guesses, SMTP failures and
  request limits use the standard error envelope. See `openapi.yaml` for shapes.

---

*本文档由模块视图重排，2026-09-14。任务编号、负责人与状态口径见 `docs/01-任务安排.md`；测试场景与答辩口径见 `docs/02-测试场景.md`；字段级细节以 `docs/api/openapi.yaml` 为准，两者冲突时以 `openapi.yaml` 为准并在同一 PR 内同步本文。*
