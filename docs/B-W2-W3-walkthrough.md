# 主力 B · W2/W3 交付与代码走读

工作目录：`D:\AAA-Finally\Doctor_Work_Platform\Doctor-Work-Platform`
功能分支：`codex/b-w2-w3`
基线：已有 B 的 W1 安全分支，含 `b3bd9fe`。本次增量不重新实现 W1，也不改 A/C/D 的业务模块。

## 1. 本次范围与实际状态

| 周次 / 任务 | 本次实现 | 状态与边界 |
|---|---|---|
| W2 T20 医嘱接口 | 医嘱表、开立/修改/软停/列表、服务端校验调用、校验结果存储、审计、数据范围、归档拒写 | B 接口完成并以测试适配器验证。当前仓库没有 A 的 T19 病历表/服务和 T21 校验引擎；未接入时返回 503，不伪造通过结果。端到端医嘱验收等待 A。 |
| W2 T25 WebSocket | JWT 握手与持续校验、参与者检查、房间广播、消息先落库、Redis 在线租约、断线清理、历史补齐、20 连接验证 | 问诊房间实现。D 的 T30 会诊模型尚不存在，会诊房间共享接入仍待联调；A 的 WebRTC 信令/通话属于 T29，不在本次实现。 |
| W2 T26 图文消息 | 文本/图片消息、受保护 StaticFiles、随机文件名、5 MiB/25MP 限制、内容识别、解码重编码、图片历史回显 | 完成。图片不是匿名公开文件；浏览器携带 Token 获取 blob 后展示和打开大图。 |
| W2 T36 自动提醒 | 规则创建/更新/停用、APScheduler 分钟触发、幂等日志、未读计数、铃铛入口、列表已读、完成操作 | 完成；时区 Asia/Shanghai，重启不补历史漏掉的分钟。 |
| W3 T27 问诊工作台 | 待接诊/进行中/已结束、接诊和结束、最近消息预览、聊天气泡、发送中/已送达/重试、向上加载、断线重连 | 完成；仅创建者与接诊医生是参与者。平台没有患者客户端，创建者可以作为患者协助人员。 |
| W3 T35 健康方案 | 创建/列表/详情/更新、目标与日期、三类条目和完成状态、方案状态变更、创建时联建/关联提醒 | 完成；通过 `terminated` 保留终止记录，契约未定义物理 DELETE。 |

部署按用户确定的「Redis + 后端 + SQLite 同一台云服务器」准备。新增独立 `compose.sqlite.yaml`，没有替换 D 的 `compose.yaml`，也没有在本次连接任何云服务器或迁移真实数据。

## 2. 建议的走读顺序

1. `backend/app/work_models.py`：B 新增的七张表。`medical_order`、`consultation`、`consult_message`、`image_upload`、`health_plan`、`reminder_rule`、`reminder_log`。特别看消息重试唯一键和提醒唯一键。
2. `backend/migrations/versions/bd9e76dbea39_b_w2_w3_orders_chat_health_and_reminders.py`：新增迁移，只创建 B 的表。`migrations/env.py` 仅增加 B 模型导入，让 Alembic 比较元数据。
3. `backend/app/work_schemas.py`：入参必填/枚举/长度/日期/cron 校验，以及 Swagger 使用的响应模型。
4. `backend/app/work_common.py`：复用 W1 当前用户与患者范围检查，统一分页和 UTC 序列化。
5. `backend/app/orders.py`：按病历取得患者，先检查范围和归档，再执行 A 的校验，最后整批写入。任何 blocked 结果使整批不落库。修改重新校验，停用不删除。看下节对接契约。
6. `backend/app/chat.py`：`room_for`（范围/参与者）、`store_message`（先落库和幂等重试）、`chat_socket`（握手、收发、清理）、`history`（稳定游标）、`checked_image` / `read_image`（文件安全）。
7. `backend/app/health_work.py`：方案与规则在同一事务创建；规则只归创建医生所有。`fire_reminders` 按医院时区生成 UTC 到期点，用数据库唯一键去重。
8. `backend/app/main.py`：只增加路由、ChatHub、提醒定时任务注册。原有临时授权任务保留；提醒有固定 job id，不按每次请求注册。
9. 前端：`ConsultationsView.vue`、`HealthPlansView.vue`、`RemindersView.vue`，共享请求在 `api/work.js`，受保护图片在 `components/ChatImage.vue`。
10. `compose.sqlite.yaml`、`frontend/nginx.conf`、`frontend/vite.config.js`：SQLite/图片持久化和 WS/上传转发。详细操作见 [单机部署指南](B-single-server-deployment.md)。

## 3. A 的医嘱对接入口（不替 A 实现）

在应用构建时安装两个真实函数：

```python
app.state.order_record_loader = load_record_for_orders
app.state.order_validator = validate_orders
```

函数约定：

```python
load_record_for_orders(db, record_id)
# 返回拥有 patient_id 和 status 属性的真实病历对象；不存在返回 None。
# 使用调用者的同一个 SQLAlchemy Session，不要自己提交事务。
# 与 A 的归档/删除流程协调事务锁，避免归档检查与写入之间出现竞态。

validate_orders(db, patient_id, items)
# items 为 OrderItemInput 字典列表；必须读取该患者的真实过敏数据及 A 的规则。
# 返回 OpenAPI 的 OrderValidateData：
{
    "overall": "warning",
    "results": [{
        "index": 0,
        "status": "warning",
        "reasons": [{"kind": "dose", "message": "A supplies the actual rule detail."}]
    }]
}
```

B 校验每个结果的 index、status、reasons 和详情结构。没有真实函数时返回 503；不存在的病历返回 404；归档病历和停用医嘱拒绝修改。测试中的 passed/blocked 函数只存在于 `tests/test_b_work.py`，没有安装到生产应用。

当前 `record_id` 有索引但没有跨模块外键，因为 A 的 `medical_record` 表尚不存在。A 合入后应同时增加关联外键迁移并落实病历的归档/删除锁。不能仅安装一个返回固定病历或固定 passed 的函数后宣称完成联调。T21 的验证预览接口、药品字典与过敏/剂量规则实现仍归 A。

## 4. HTTP / WS 对接重点

| 功能 | 接口 |
|---|---|
| 医嘱 | GET/POST `/api/emr/orders`；PATCH `/api/emr/orders/{id}`；POST `/api/emr/orders/{id}/stop` |
| 问诊 | GET/POST `/api/consultations`；GET `/{id}`；POST `/{id}/accept`、`/{id}/end` |
| 消息 | GET/POST `/api/consultations/{id}/messages` |
| 图片 | POST `/api/uploads/images`（multipart `file`）；GET `/uploads/{filename}`（Bearer） |
| 实时 | `/ws/chat/{room_id}?token=...`，room_id 当前为问诊 ID |
| 方案 | GET/POST `/api/health-plans`；GET/PATCH `/api/health-plans/{id}` |
| 规则 | GET/POST `/api/reminder-rules`；PATCH `/api/reminder-rules/{id}` |
| 提醒 | GET `/api/reminders`、`/api/reminders/unread-count`；POST `/api/reminders/{id}/done` |

HTTP JSON 统一 `{code, message, data}`，列表复用 `{items,total,page,size}`；医嘱和规则列表按现有契约为数组。计划 PATCH 仍使用契约中的完整 `HealthPlanWriteRequest`，不是任意字段的局部 PATCH。提醒规则 PATCH 支持单独 `{active:false}`。方案更新的 `reminder_rule_ids` 为关联已有规则，不解绑已有规则；停用请走规则 PATCH。

消息默认按 ID 倒序取最近 20 条。向上加载用 `before_id`；重连用 `after_id`，该模式按 ID 正序返回。两种游标不能混用。前端合并时按数据库 ID 去重排序。可选 `client_id` 作为房间/发送者范围内的重试键，重复相同内容返回原记录，冲突内容返回 409，避免“已保存但客户端未收到确认”后的重复消息。

WS 消息格式：

```json
{"type":"message","data":{"content":"Hello","client_id":"a-client-generated-unique-id"}}
```

服务端 `message` 事件返回持久化后的消息。`status` 同步接诊/结束；`joined` / `left` 表示连接加入/退出；`ping` 需客户端 `pong`；`error` 包含错误和可用时的 client_id。每条连接 Redis 租约 60 秒，每 20 秒续期，断开立即删除。未通过 JWT、被禁用、被注销或失去患者访问权限的连接不能继续收发。队列满时要求客户端重连，从 SQLite 补齐。

视频相关 `call_offer/call_answer/ice_candidate` 暂未安装，不把发送这些事件伪装成完成 T29。未来会诊接入必须明确房间类型，不能把 D 的 meeting 整数 ID 与 consultation ID 直接混查。

## 5. 测试与复核

- 新增 `tests/test_b_work.py`：8 个集成场景，覆盖 50 条历史分页/游标、房间参与者与跨科室拒绝、消息重试、结束只读、WS 鉴权/在线清理/补齐、图片类型/大小/路径/鉴权、方案原子写入/日期/范围、提醒幂等/已读/停用/时区/方案终止，以及医嘱依赖缺失/生命周期/整批阻断/审计。
- 20 个同时在线连接：本机 TestClient + FakeRedis + 临时 SQLite，消息持久化并广播到全部连接约 **322 ms**。这是本地测试环境数据，不是云服务器或真实 Redis 的 SLA。
- 真实浏览器（headless Edge）连接临时 Uvicorn + Vite + SQLite + FakeRedis：跑通新建问诊、第二账号接诊、文本发送并收到 Delivered、结束只读；创建健康方案同时创建提醒；规则停用。浏览器无 pageerror，截图已检查。
- 前端原有 3 项测试和生产构建通过。原有大包体积警告仍存在。
- Alembic 从旧 head 升级到新 head、`alembic check` 和 Ruff 检查通过；OpenAPI 与 SQLite Compose YAML 已解析检查。
- 未运行 Docker 容器或真实云服务器；当前电脑没有可用 Docker 命令。上线还需真实 Redis、SMTP、HTTPS 和卷备份恢复验证。

全量回归结果见文末“最终验证”。旧 `test_auth_grants.py` 仅调整一条断言：检查 `expire_temp_grants` 注册一次，而不是假定整个应用只有一个任务。这是新增 T36 必需的集成适配，未改 A 的授权业务。

Windows 的原有人脸测试把约 280 万字符的参数放进测试 ID。为运行全部原始参数而不改人脸测试文件，验证时通过临时 pytest 插件把超长字符串 ID 缩短（测试值不变）：

```python
def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, str) and len(val) > 200:
        return f"{argname}-length-{len(val)}"
```

普通 B 验证直接执行 `uv run pytest tests/test_b_work.py -q -s` 即可。全量验证的临时插件不属于运行时代码。

## 6. 手动验收入口

1. 准备两个同科室已激活医生和一个患者；患者编号从现有患者列表取得。
2. 账号一进入 Consultations，填写患者编号，New consultation。
3. 账号二在 Waiting 列表 Accept；两个账号进入同一会话，发送文字和小图片。
4. 刷新页面检查历史和图片仍在；结束后输入框禁用。跨科室账号、同科室非参与者分别验证不能读消息。
5. 在 Health Plans 创建方案，填写日期与条目，勾选 linked reminder；在 Reminders 检查关联规则。
6. 将规则设为 `* * * * *`，离开提醒列表等待后看铃铛未读数。回列表标记已读，停用后历史保留、不新增。
7. 医嘱目前先用 B 测试检查接口；等 A 接入真实病历和引擎后再跑真实开立验收，不能以测试适配器作为业务验收结果。

## 7. 最终验证（2026-09-13）

- 后端：**84 passed**，全量原始测试值均运行；仅通过临时插件缩短超长参数的测试名称，耗时 149.55 秒。
- B 新增验收：8 passed（包含在上述 84 项内）。
- 前端原有测试：3 passed；生产构建通过。
- Ruff check / format：通过；Alembic check：无模型/迁移差异。
- 页面实测：问诊生命周期、创建方案并关联提醒、规则停用通过。
- 未完成的跨成员验收：A 的 T19/T21 真实医嘱集成、D 的会诊房间接入；未冒充完成。
- 未执行云部署：本次交付配置和指南；没有服务器地址/SSH/真实 SMTP 输入，当前环境也没有 Docker 命令。
