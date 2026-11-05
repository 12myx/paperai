# Railway 部署

## 1. 连接仓库

Railway → New Project → Deploy from GitHub → 选择 paperlens-demo。

项目根目录已有：

- Dockerfile（Node 构建前端 + Python 运行）
- railway.json（healthcheck /api/health）
- .dockerignore（排除 data、node_modules、backups）

## 2. 必填变量

在 Railway 服务 Variables 中设置：

    PAPERLENS_ENVIRONMENT=production
    PAPERLENS_SECRET_KEY=<64 字符随机值>
    PAPERLENS_DATABASE_URL=sqlite:///./data/paperlens.db
    PAPERLENS_STORAGE_DIR=./data/storage

生成密钥：

    python -c "import secrets; print(secrets.token_urlsafe(48))"

可选：

    PAPERLENS_RATE_LIMIT_PER_MINUTE=120
    PAPERLENS_CORS_ORIGINS=https://<your-service>.up.railway.app
    DEEPSEEK_API_KEY=...
    PAPERLENS_DEEPSEEK_MODEL=deepseek-chat

## 3. 必须挂载持久卷

Railway 默认文件系统是临时的，容器重启会清空 SQLite 与 PDF。

- 添加 Volume
- Mount path：/app/backend/data

这样数据库和 storage 才持久化。

## 4. 域名

Settings → Networking → Generate Domain。

首次访问后注册账号；如果需要演示数据，可在容器内运行：

    cd /app/backend
    QA_PASSWORD='<demo-password>' python scripts/qa_seed.py

注意：qa_seed 会通过 http://127.0.0.1:8000 调用 API，适合在容器内执行。

## 5. 健康检查

    https://<domain>/api/health

应返回 environment=production。

## 6. 限制

- 单实例 SQLite；不要横向扩容多个副本。
- Railway 免费/试用额度、休眠与卷计费以平台为准。
- 没有 Redis/Celery；解析队列是进程内单 worker。
- 首次构建会安装 PyMuPDF/Node，可能需要几分钟。
- 如果要接 Postgres：设置 PAPERLENS_DATABASE_URL，并先做迁移/并发/备份回归。
