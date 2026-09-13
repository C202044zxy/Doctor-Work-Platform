# B 主力开发交付与代码走读

任务：T03 Redis/配置、T06 邮箱验证码、T08 RBAC、T09 数据范围、T11 审计中间件。

本地仓库：`D:\AAA-Finally\Doctor_Work_Platform\Doctor-Work-Platform`

GitHub：<https://github.com/C202044zxy/Doctor-Work-Platform>

交付分支：`codex/b-security-foundation`。最终实现基于最新 main `61b78d5`，保留 A 的认证/注册/临时授权及 T13/T14 患者资料、加密、过敏记录实现。前端文件与最新 main 完全一致，本次没有修改样式、布局、路由或页面逻辑。

## 1. 交付内容与走读入口

| 任务 | 本次实现 | 首先阅读 |
|---|---|---|
| T03 | 复用 Redis 连接池/get_redis；统一 page/size 依赖；404/422/500 同构错误；健康检查；秘密不使用默认有效值、不出现在配置 repr | app/config.py、dependencies.py、main.py |
| T06 | 在 A 的票据合同上实现原子发送配额预留；六位码、300s TTL、60s 冷却、每日20次；TLS/超时；重发后票据同步续期；一次性并发消费验证 | app/otp.py、auth.py |
| T08 | 声明式三角色矩阵；默认保护直接/包含路由；患者读写权限；其他模块可复用 require_permission；实时数据库角色/状态 | app/security.py、auth.current_user |
| T09 | 本科室与有效临时授权的统一 SQL 条件；列表/count/详情/过敏数据复用；admin 豁免；越界患者404 | app/patients.py、main.py、allergies.py、grants.py |
| T11 | 所有写请求自动留痕；敏感患者读手动标记；独立审计事务；授权到期后台审计；扩展元数据；只增触发器与最小权限脚本 | app/audit.py、models.py、迁移、scripts/audit_permissions.sql |

以上相对最新 main 的增量才是 B 本次工作，A 已有的密码/JWT、注册、临时授权业务不重复认领。

## 2. 推荐走读顺序

1. `backend/app/security.py`：PERMISSIONS 是后端唯一角色权限矩阵；ProtectedRoute 默认校验业务路由，ProtectedFastAPI.include_router 保证导入路由也不会遗漏默认认证。匿名路径逐条列出，不使用宽泛的 `/auth/*` 放行。
2. `backend/app/auth.py`：沿用 A 的用户名登录和 DTO；密码验证仅生成 ticket，send-code 根据票据查真实邮箱，verify-code 才签 JWT。current_user 每次查询数据库角色、科室和禁用状态，旧 Token 中的角色无法维持已撤销权限。
3. `backend/app/otp.py`：WATCH/MULTI 同时预留冷却和每日配额，多请求并发只有一个可发送。SMTP 失败仍占用冷却及配额，防止无限重试轰炸。
4. `backend/app/patients.py`：patient_scope = 本科室 OR 有效临时授权；授权条件同时检查 grantee、patient、is_valid 和实际过期时间，不依赖每分钟定时扫描是否已运行。visible_patient 统一处理软删除和404。
5. `backend/app/main.py`：保留患者编号、组合查询、加密和过敏实现；列表 items/count 使用同一 scope；旧 `_audit` 改为记录请求元数据，实际写日志发生在响应中间件。
6. `backend/app/audit.py`：finally 自动处理 POST/PUT/PATCH/DELETE；mark_audit 显式描述敏感读与业务对象；独立 session 提交，失败只输出固定告警，不输出异常或连接秘密。
7. `backend/app/grants.py`：授权创建/撤销接入相同标记；到期扫描先提交授权状态，再独立持久化已获胜更新的审计，避免日志故障回滚授权回收。
8. `backend/migrations/versions/c0311060809b_security_foundation.py`：接在 A 的 e3b6c9d24f75 后面，保留旧记录，扩展审计字段；SQLite/MySQL 触发器拒绝 UPDATE/DELETE。
9. `backend/tests/test_security.py`：角色15组合、科室/角色实时变更、并发发码与消费、审计字段/故障/不可改删、默认路由保护和SMTP故障。

## 3. 接口合同

以 `docs/api/openapi.yaml` 为请求/响应合同，不引入第二套邮箱登录或数字患者ID接口。

| 请求 | 合同/行为 |
|---|---|
| POST /api/auth/login | `{username,password}` → `{ticket,expires_in}` |
| POST /api/auth/send-code | `{ticket}` → `{ok:true}`；发送与重发均使用此入口 |
| POST /api/auth/verify-code | `{ticket,code}` → `{access_token,token_type,expires_in,user}` |
| GET /api/me | 当前数据库用户资料 |
| POST /api/auth/logout | 黑名单 TTL = JWT 剩余有效时间 |
| GET /api/patients | `page/size/name/patient_no/symptom_tags/admitted_from/admitted_to`，返回 items/total/page/size |
| GET/PATCH/DELETE /api/patients/{patient_no} | 使用 P2026... 业务编号；患者不在数据范围或已软删除均404 |
| GET /health、GET /api/health | 相同合同；Redis断连200，data.redis=down |
| GET /api/health/live、/api/health/ready | 保留现有部署脚本的 status/checks；增加统一 code/message/data；ready依赖故障503 |

标准业务响应为 `{code:0,message:"ok",data:...}`；错误为 `{code:HTTP状态,message:"说明",data:null}`，没有 error.message 第二套错误合同。

**Redis 故障取舍**：健康检查仍可用；受保护接口必须检查 JWT 登出黑名单，Redis 不可用返回503而不跳过认证。这与早期签收细则“登录以外不受影响”的字面描述不同，是为了避免已登出 Token 在 Redis 宕机时恢复权限。

## 4. 权限矩阵与模块接入

| 角色 | 患者读写 | emr.review | audit.read/export | user.manage | template.manage |
|---|---|---|---|---|---|
| junior | 允许 | 403 | 403 | 403 | 403 |
| senior | 允许 | 允许 | 403 | 403 | 403 |
| admin | 允许 | 403 | 允许 | 允许 | 允许 |

admin 按签收矩阵不自动获得临床审阅权限。senior/admin 可以管理临时授权；senior只能对本科室患者授权，不能转授权别人临时开放的患者。

新增资源应在路由声明 `dependencies=[Depends(require_permission("emr.review"))]` 等。默认认证只是底线，不替代资源权限。患者相关服务必须使用 patient_scope/visible_patient；内部无用户的低层过敏读取仅用于可信后台计算，HTTP 路由必须通过带 user 的 session。

15组合中的 `/api/contract/*` 是测试内临时路由，**不在生产应用**。病历审阅业务、审计查询导出、用户管理和模板管理业务属于其他模块；B交付可复用权限和验收矩阵，不用固定200假接口冒充业务实现。T12/EMR敏感GET还需调用 `mark_audit(request, "audit.export", "audit_log")` / `mark_audit(request, "emr.view", "medical_record", id)`。

最新 main 已有注册和人脸路由，因此匿名白名单保留这些已存在的认证协议入口；本次不修改其实现或前端入口。WebSocket未来需单独接入握手认证，HTTP依赖不自动保护WS。

## 5. 验证码与审计细节

- 验证码使用 secrets 生成，Redis key 为 `auth:code:{user_id}`，只存绑定 ticket 的 HMAC-SHA256 摘要；ticket key 也使用 SHA256。原始码仅用于邮件发送。
- 成功写码时 OTP 和对应 ticket 同步获得300秒TTL，避免临近过期时重发后“新码刚收到票据已过期”。重发重置该票据的错误计数。
- 每账号60秒冷却、UTC每日20次；429消息含剩余秒数或每日上限说明。验证错码5次销毁票据/码；成功验证通过WATCH/MULTI原子删除。
- SMTP默认超时10秒，可配置1~30秒范围（实际字段>0且<=30）；465为隐式TLS，其他端口要求STARTTLS，不接受明文SMTP；失败502，正文不含服务器异常细节。
- 审计字段：user_id、created_at、ip、method、路由模板path、action、object_type/id、patient_id、detail、result、status_code。认证失败且身份未验证时 user_id 为空。
- path记录路由模板；具体患者编号记录在 object_id。保留 T14 原有过敏删除 detail（编码、名称、严重程度），不记录 request body、查询串、密码、token、验证码、照片、患者正文。
- IP只使用可信连接来源，不直接相信客户端传入 X-Forwarded-For。代理部署需另配 Uvicorn 信任源。
- 日志提交失败不影响患者操作或授权回收；会输出固定 `Audit persistence failed; business response preserved` 告警。独立事务不承诺进程突然崩溃时零丢失。

## 6. 数据库部署和配置

新迁移只扩展审计表，不重建 A 的用户/授权模型。audit_logs.patient_id 改为可空，以容纳登录等不关联患者的事件。

MySQL最小权限模板：`scripts/audit_permissions.sql`。使用管理账号迁移/seed后创建全新的 doctor_runtime 账号，业务表授予所需读写，audit_logs只SELECT/INSERT。脚本中的本地密码占位符必须自行替换，不能提交真实值。不要对该账号授予 database.* / *.* 广域权限；MySQL权限叠加，表级REVOKE不能抵消广域授权。默认Compose账号用于开发迁移，不代表生产最小权限账号。

触发器还可阻止开发账号UPDATE/DELETE；不阻止有DDL权限的管理员DROP/TRUNCATE，runtime无DDL权限是前提。降级迁移会删除触发器和新增审计列，属于有损管理操作，不用于日常运行。

本地 `backend/.env` 最少配置：

```dotenv
DATABASE_URL=sqlite:///./doctor.db
REDIS_URL=redis://127.0.0.1:6379/0
JWT_SECRET=<本地随机生成至少32字符>
PATIENT_DATA_KEY=<本地数据加密密钥>
SMTP_HOST=<实际SMTP服务器>
SMTP_PORT=465
SMTP_USERNAME=<邮箱账号>
SMTP_PASSWORD=<邮箱授权码>
SMTP_FROM=<发件邮箱>
SMTP_STARTTLS=true
```

JWT不再使用有效的开发默认密钥：未配置时认证返回503。患者加密配置属于T13，本次保持最新main的行为；**已有加密数据必须继续使用原 PATIENT_DATA_KEY，不能直接换值**。Compose读取根目录 `.env`，本机uv命令从backend读取 `.env`。JWT和SMTP密码不进入Git、不输出日志，配置对象的repr也隐藏这些值。

创建本地账号（沿用A工具，密码交互输入）：

```powershell
cd D:\AAA-Finally\Doctor_Work_Platform\Doctor-Work-Platform\backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.seed
uv run python -m app.create_user --username dr_wang --name "Dr Wang" --email your-email@example.com --title junior --department "General Medicine"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 7. 验证与未实测项

后端除人脸参数化文件外的66项全部通过，B安全用例单独通过；人脸文件中不含超长参数的5项也通过。最新main的人脸测试包含约280万字符的参数值，pytest在Windows上把它用于临时路径时触发路径长度错误；该问题不属于B任务，按分工边界未修改这份测试。Ruff检查/格式门禁、新建SQLite迁移、Alembic模型一致性检查均通过。前端3项现有测试和生产构建通过，现有大分包提示不属于此次安全功能错误。

```powershell
cd D:\AAA-Finally\Doctor_Work_Platform\Doctor-Work-Platform\backend
uv run pytest -q
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run alembic check
```

真实服务检查已加入GitHub CI：`docker compose exec -T backend .venv/bin/python -m app.verify_services`。它验证真实Redis原子发送预约、OTP摘要与TTL，及MySQL审计改删拒绝；只清理随机测试账户的Redis key，不flushdb，保留一条 integration.verify 审计记录。

仍需真实环境签收：SMTP是否60秒内收信，以及以生产runtime账号验证最小权限。当前没有收到本机SMTP配置，因此不把替身测试当作真实收信验收。真实MySQL/Redis结果以CI为准，本地SQLite/fakeredis不代替它。
