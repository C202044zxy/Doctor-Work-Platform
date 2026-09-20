# main 合并、升级与 PR 指南

2026-09-20：在 **D 盘原仓库** `D:\AAA-Finally\Doctor_Work_Platform\Doctor-Work-Platform`，将 `main@c98324e` 合入 `codex/b-w2-w3`。保留用户提交 `9c72ea8` 及此前 M3、热更新、Redis、短信和视频模式修复。C 盘未写入本次修改。

## 解决的冲突

- 12 个文本冲突文件按功能合并，包含应用装配、依赖、导航、登录、问诊页面、建库契约与任务文档。
- main 的患者搜索/分组、病历/医嘱、远程会诊、健康管理与原分支 M3 并存；Patient consultation 已挂载真实工作台。
- 医嘱同名表隔离为 main `medical_order` 与旧 `legacy_medical_order`；两边数据均保留。合并 head 为 `e6a31c29d408`。
- 同名健康/提醒/医嘱路径由 main 接管；兼容 API 位于 `/api/legacy/*`，兼容健康页面位于 `/legacy/*`。main 的未读字段是 `unread`，旧接口是 `unread_count`。
- 清理重复设置字段与模型类名，提醒 job 使用独立 ID，避免自动合并后启动/调度错误。

## 在已有 D 盘数据库上启动

1. 停止正在运行的前后端服务，保持 Docker Desktop 运行。
2. 备份 `backend/doctor.db`，并保留原 `backend/.env` 中的密钥。以下从仓库根执行，用 SQLite backup 保存当前库：

   ```powershell
   cd backend
   uv run python -c "import sqlite3; from pathlib import Path; from datetime import datetime; p=Path('../backups'); p.mkdir(exist_ok=True); source=sqlite3.connect('doctor.db'); target=sqlite3.connect(p / ('before-main-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')); source.backup(target); target.close(); source.close()"
   cd ..
   ```

3. 按原方式启动（这次增加依赖，第一次不要加 SkipInstall）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
   ```

   脚本更新依赖、启动开发 Redis、执行 `alembic upgrade head` 和幂等种子，随后启动热更新服务。不要删除数据库、不要 `alembic stamp` 跳过迁移，也不要用默认 `build_db.py` 重建手测数据。

4. `/api/health/ready` 应返回 200，db 与 redis 均为 ok。若 Redis 不可用，确认 Docker 已启动，执行 `docker compose -f compose.dev.yaml ps`；开发端口是 16379。

本轮测试使用 `backend/runtime/merge-verification.db` 和 8001/5174 隔离端口，没有迁移或覆盖现有 `backend/doctor.db`。正式开发仍用 8000/5173，上述启动脚本会迁移现有库。

## 手动验收重点

1. 登录选择 SMS (simulated)，发送、查看、验证；应明确显示模拟。另查 Face 模式说明保留“无实际人脸比对”。
2. Consultations → Patient consultation：两账号打开相同房间，等待/进行中/已结束三态，图文、历史加载与记录 CSV 正常。
3. 同机视频：一端 Camera + microphone，另一端 Receive only；后者不申请设备权限，仍能收到视频/音频。断开后重新呼叫，确认摄像头释放。详见《视频通话同机测试与排错》。
4. 切换 Remote consultation：展示 main 的会诊列表与流程；回到 Patient consultation 可重新进入房间。
5. Patients：新增/搜索患者、症状标签与分组；详情 Health data 的体征、方案和提醒正常。Dashboard 未读数来自 main 提醒。
6. Medical Records / My submissions / Review Queue：按角色执行 main 的病历、医嘱、提交/审阅流程；不再被旧医嘱的 503 适配器入口遮挡。
7. 若以前录过旧健康方案，访问 `/legacy/health-plans`、`/legacy/reminders` 查看。旧数据不会自动合入 main 新模块。

## 验证记录

- 后端全量：202 passed；新增合并及日志回归：4 passed。
- 前端：46 passed；生产构建通过，既有包体积警告。
- 空库：36 表、2 审计触发器；alembic check 无差异。
- 原 M3 与 main 已发布 head 的数据保留升级、回滚、标准/兼容接口隔离通过。
- 浏览器：双账号图文、双向合成音视频、只接收模式、设备争用后恢复、30 秒延迟授权、挂断/取消释放设备、记录筛选与 CSV、密码→短信模拟→JWT 登录全部通过。
- M3/M5 标签切换通过：加载真实会诊 API、保留 room 参数、返回后恢复问诊；修复后的真实服务日志无格式异常。
- 修复原日志脱敏器清空 Uvicorn 访问日志参数的问题；保留令牌脱敏和访问日志格式。
- 自动化使用合成媒体；物理摄像头/麦克风、跨设备网络与 Excel 人工验收仍由手测完成。

## 手动创建 PR

使用 D 盘的 `codex/b-w2-w3` 分支，PR 的 base 选 `main`，compare 选 `codex/b-w2-w3`。合并提交会包含 main 历史，因此无需再复制 C 盘文件，也不要重复合并同一 main 提交。创建前刷新 GitHub，若 main 又有新增提交，再检查冲突。

建议标题：`feat: integrate M3 consultations and simulated SMS with main`。

建议说明：保留 M3 图文、记录和同机视频模式，整合 main 的患者/M4/M5/M6 页面；修复重复路由与医嘱表冲突，兼容保留原分支数据。注明本页测试结果、真实硬件仍待手测，以及两条历史迁移增加兼容判断的原因。
