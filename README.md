# Doctor Work Platform

Vue 3 / Vite / Element Plus 前端，FastAPI / SQLAlchemy / Alembic 后端，SQLite 数据库，Redis 认证与在线状态。

## 开发启动（保存源码自动更新）

安装 uv、Node.js 22.12+，启动 Docker Desktop，然后在仓库根执行：

```powershell
.\scripts\dev.ps1
```

依赖已安装后：`.\scripts\dev.ps1 -SkipInstall`；仅初始化：`.\scripts\dev.ps1 -NoServe`。执行策略阻止脚本时使用 `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1`。

Linux/macOS（Bash 4.3+）：`bash scripts/dev.sh`；再次启动可用 `bash scripts/dev.sh local --skip-install`。

开发模式只把 Redis 放在 Docker，前端由本机 Vite 提供 HMR，后端由本机 Uvicorn `--reload` 自动重载。不是构建前后端镜像。

- 前端：http://127.0.0.1:5173
- API：http://127.0.0.1:8000/docs
- Redis：127.0.0.1:16379（仅本机）
- 本地数据：`backend/doctor.db`、`backend/uploads/`；Windows 日志：`backend/runtime/`。

**完整步骤、账号、双浏览器图文/视频验收、停止方式与排错：[开发模式启动与手测](docs/开发模式启动与手测.md)。**

首次启动仅在缺失时生成 `backend/.env` 随机密钥。已有配置不覆盖，已有数据库必须保留原加密密钥。Redis 是认证硬依赖。`/health` 与 `/api/health` 依赖异常仍返回 200；`/api/health/ready` 则会返回 503。

## 当前交付

M3：三态问诊、WebSocket 图文、历史补齐、受保护图片、记录检索/CSV、WebRTC 视频信令及通话记录。详见 [M3 架构与工作记录](docs/M3-架构与工作记录.md)。状态为**部分完成**：真实音视频硬件、局域网 HTTPS 和 M5 房间接入仍需验收/联调。

主线认证、患者和审计代码已整合。原分支健康方案、提醒、医嘱对接仍保留；医嘱需要 M4 真实病历/校验器，未接入时返回 503。其他未完成页面不能按截图宣称完成。

种子账号 `admin_zhang` / `dr_li` / `dr_wang` / `dr_chen`，初始密码 `Demo@2026`。正常邮箱登录需要 SMTP 和可收信邮箱；种子邮箱是 example.test。短信/人脸页面是模拟 provider，不能替代真实登录。仅测本地业务可使用 `uv run python -m app.dev_session --username dr_wang`，操作见启动指南；不新增 HTTP 免密登录。

## 验证

后端目录执行：

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run alembic upgrade head
uv run alembic check
```

前端目录执行：

```powershell
npm ci
npm test
npm run build
```

独立空库验证（仓库根）：

```powershell
uv run --project backend python scripts/build_db.py --db backend/runtime/verification.db
```

日常启动只迁移与幂等补种子，不重建数据库。建库工具会备份目标已有数据后重建，不要对运行中的业务库执行。数据库、.env、uploads、runtime 和依赖都不进 Git。

## 发布与存储

`scripts/dev.ps1 docker` / `scripts/dev.sh docker` 仍表示完整镜像构建模式，使用 `compose.yaml`；根 `.env` 按 `.env.example` 配置。已有独立服务器配置 `compose.sqlite.yaml` 和 `.env.server` 可继续使用。开发模式不需要每次运行这两个完整栈。

发布时使用一个 API worker。图文广播/视频信令为进程内状态；多 worker 部署前需增加 Redis Pub/Sub 与分布式呼叫状态。完整 Compose 的 SQLite 与图片都保存在 `/data` 卷，备份应包含数据库与 uploads。图片不自动清理，未发送的上传也会保留；删除和保留策略需业务确认。

WebRTC 默认无 STUN/TURN，只面向同机/可直连局域网验证；其他设备摄像头访问需可信 HTTPS，公网通常需 TURN。只保存通话元数据，不保存音视频或模拟回放。

## 文档权威

- [文档索引](docs/README.md)
- [任务与负责人](docs/01-任务安排.md)
- [测试场景及演示基线](docs/02-测试场景.md)
- [实现现状](docs/03-实现现状.md)
- [API 索引](docs/api/API-索引.md) / [字段契约](docs/api/openapi.yaml)

任务按 M0–M9 / S1–S6 / D01–D07 编号。新启动、架构文档是这些权威文档的操作补充，不另设任务清单。
