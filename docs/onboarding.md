# 新成员启动

日常开发统一使用 [开发模式启动与手测](开发模式启动与手测.md)。从仓库根运行 `.\scripts\dev.ps1`，Docker 只运行 Redis；前后端在本机热更新。

首次阅读顺序：`README.md` → 开发模式启动与手测 → `01-任务安排.md` → `02-测试场景.md` → `03-实现现状.md`。字段以 `api/openapi.yaml` 为准。

不要拿旧完整镜像的 8080 页面验证本地源码变更；不要将 Docker 数据卷与本地 SQLite 视为同一数据库。完整发布仍使用 Compose 镜像模式，已有服务器命令见 `Docker-reproduction.md`。
