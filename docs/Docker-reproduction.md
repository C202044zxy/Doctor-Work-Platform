# Windows 新成员：用 Docker 从零启动

这条流程只需要 Docker Desktop 和同一份项目源码，不要求本机安装 Python、Node、uv、Redis 或数据库。SQLite 是容器数据卷中的文件。

## 第一次准备

1. 安装并启动 [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)，使用 WSL 2 / Linux containers。Docker 官方的 [WSL 2 配置说明](https://docs.docker.com/desktop/features/wsl/) 可用于排查虚拟化和 WSL 问题。
2. 在新的 PowerShell 窗口验证 `docker version` 和 `docker compose version`。前者必须显示 Server 部分，否则 Docker 引擎还没启动。
3. 拿到包含 `scripts/docker.ps1` 和 `compose.sqlite.yaml` 的完整源码，并进入仓库根目录。目前 W2/W3 仍未推送；新成员只拉 main 不会得到这份代码。暂时可由负责人共享源码包，不要复制 `.venv`、`node_modules`、`.env.server` 或真实患者数据库。

## 初始化配置、启动、创建管理员

在仓库根目录依次执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 init
notepad .env.server
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 up
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 account
```

`init` 通过一次性 Python 容器生成随机 JWT 和患者加密密钥，已存在的 `.env.server` 原样保留，不会因为重复启动而更换密钥。它不会在终端打印密钥。

编辑 `.env.server` 时配置团队测试 SMTP：

```dotenv
SMTP_HOST=你的SMTP服务器
SMTP_PORT=465
SMTP_STARTTLS=false
SMTP_FROM=发件邮箱
SMTP_USERNAME=发件邮箱
SMTP_PASSWORD='邮箱SMTP授权码'
```

如服务商要求 STARTTLS，使用 `SMTP_PORT=587`、`SMTP_STARTTLS=true`。密码是邮箱服务商的 SMTP 授权码/凭据；带 `$`、`#` 等特殊字符时用单引号包住。配置由团队自行提供，不放进 Git。

`up` 构建镜像，自动建表/迁移，初始化 General Medicine、Cardiology 两个科室和 admin/senior/junior 三个角色，然后检查数据库、Redis、上传目录和迁移版本。整个过程不使用宿主机的 Python/Node 环境。

`account` 在后端容器里运行现有的账号创建工具，依次填写：

| 提示 | 第一个账号填写示例 |
|---|---|
| Username | admin |
| Display name | Local Administrator |
| Email | 自己能够收验证码的邮箱 |
| Role | admin |
| Department | General Medicine |
| Password / Repeat password | 自己设置至少 8 位密码，输入不回显 |

该工具创建 active 账号，可以直接进入密码＋邮件验证码登录流程。不会创建公开默认密码，不会覆盖同名账号。需要测试医生时重复运行 `account` 并选择 junior 或 senior。

打开 [本机系统](http://127.0.0.1:8080)，使用刚创建的账号登录。没有配置 SMTP 时可以验证服务已启动，但**不能完成邮件验证码登录**；`up/check` 会明确报告这一状态。seed 只初始化科室和角色，没有默认患者、医生账号或业务数据，这是新数据库的正常状态。

## 每天使用

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 up
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 status
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 check
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 logs
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 down
```

代码更新或修改 `.env.server` 后运行 `up`，不要只运行 `restart`：已有容器需要重建才能使用新环境变量。`down` 保留 SQLite、图片和 Redis 数据卷；不要使用 `down -v`，否则会删数据。不要删除密钥文件后在旧数据库上重新生成患者加密密钥。

macOS/Linux 对应 `bash scripts/docker.sh init|up|account|check|status|logs|down`。脚本明确选择 SQLite Compose，旧的 `scripts/dev.ps1 docker` 仍是 MySQL 开发栈，不要混用。

## “同样的源码”和“同样的镜像”

依赖由 `uv.lock`、`package-lock.json` 锁定；Docker 内明确使用 Python 3.12、Node 22 和容器系统，uv 版本与当前项目工具链统一。构建基础镜像标签仍可能更新，不声称源码重建可产生逐字节相同的镜像。

如果同学网络下载依赖有困难，可由有 Docker 的成员构建一次，然后导出相同架构的镜像：

```powershell
docker save -o doctor-work-images.tar doctor-work-backend:local doctor-work-frontend:local redis:7-alpine
```

接收者拿到源码和镜像包后：

```powershell
docker load -i doctor-work-images.tar
# 在源码根目录，用已载入镜像里的 Python 生成自己的配置，无需下载引导镜像：
docker run --rm --mount "type=bind,source=$($PWD.Path),target=/workspace" -w /workspace doctor-work-backend:local /app/.venv/bin/python scripts/init_docker.py
notepad .env.server
docker compose --env-file .env.server -f compose.sqlite.yaml up --no-build --pull never --detach --wait
powershell -ExecutionPolicy Bypass -File .\scripts\docker.ps1 account
```

镜像包不包含命名卷中的账号/患者数据，也不要附带负责人的真实密钥。这里假设 `APP_IMAGE_TAG=local` 默认值；如改了该变量，导出/载入时使用对应标签。x86-64 Windows 与 ARM 电脑应构建/分发匹配架构的镜像。

## 常见问题

| 现象 | 检查 |
|---|---|
| docker 命令不存在 | 安装 Docker Desktop，重开终端 |
| Cannot connect to Docker daemon | 启动 Docker Desktop，确认 Linux containers/WSL 2 正常 |
| Cannot find scripts/docker.ps1 | 源码版本不对，或当前目录不是仓库根目录 |
| JWT_SECRET is missing | 先执行 init，不要拿空白示例当配置文件 |
| 8080 被占用 | `.env.server` 中设 `HTTP_PORT=8081`，再 up，访问对应端口 |
| 登录账户不存在 | 执行 account；数据库 seed 不创建管理员 |
| SMTP requires TLS / Email delivery failed | 检查465隐式TLS或587 STARTTLS、授权码、出站网络与发件地址 |
| health 显示正常但无患者 | 新卷没有业务数据，先创建患者 |
| 镜像拉取超时 | 检查 Docker Desktop 代理和网络；或用已构建镜像包 |
| 换目录后数据像消失了 | Compose 默认按项目目录命名卷，确认使用原项目名/原数据卷；不要先重建账号或覆盖旧数据 |

真实云服务器部署继续参考 [B 单机部署说明](B-single-server-deployment.md)。此开发入口不会连接你的云服务器，也不推送代码。

验证说明：当前开发机未安装可用 Docker，无法本机执行镜像构建；配置初始化和启动脚本已做静态/隔离验证。新增 `.github/workflows/sqlite-docker.yml` 在有 Docker 的 Linux runner 上执行冷启动、代理健康检查和重启验证；未推送前它不会运行。
