# PaperLens 部署手册

## 0. Railway（推荐）

见 [RAILWAY.md](RAILWAY.md)。Railway 构建会使用仓库根目录 Dockerfile，数据卷必须挂载到 /app/backend/data。

## 1. 本机生产启动

    powershell -ExecutionPolicy Bypass -File deploy/start-production.ps1

- 读取 deploy/.env.production（已被 .gitignore 忽略）
- 以 production 模式运行，静态前端由 FastAPI 托管
- 地址：http://127.0.0.1:8000
- 局域网：http://<本机局域网 IP>:8000

必须确认：

- PAPERLENS_SECRET_KEY 至少 32 字符
- CORS 只列可信来源
- 数据目录有备份

## 2. Docker

Docker 当前机器未安装，以下配置未在本机执行：

    docker compose up -d --build

- Dockerfile：Node 构建前端 + Python 运行后端
- compose 挂载 ./backend/data，保留 SQLite 与 storage
- 健康检查：/api/health

生产建议：外部 PostgreSQL，或至少把 data 放在持久卷并每日备份。

## 3. 反向代理 / HTTPS

deploy/nginx.conf 是 HTTP 反代模板。生产需要：

1. 域名 A/AAAA 记录指向服务器
2. nginx + certbot（或 Caddy）签发 TLS
3. 只暴露 443，8000 仅监听内网
4. 设置 client_max_body_size 55m，SSE 关闭 proxy_buffering

## 4. 临时公网隧道

    cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate

会得到 https://*.trycloudflare.com 临时地址。特点：

- 无需域名/账号
- 进程停止即失效
- 不适合作为长期生产地址

命名隧道模板见 deploy/cloudflared.example.yml。

## 5. 备份与恢复

    cd backend
    python scripts/backup.py create
    python scripts/backup.py inspect backups/xxx.zip
    python scripts/backup.py restore backups/xxx.zip --yes

恢复会替换数据库与 storage，先保存 .pre-restore-*。

## 6. 健康检查

    curl http://127.0.0.1:8000/api/health
    curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/ops/metrics

指标包含队列、RAG 缓存、限流、数据库方言。

## 7. Postgres

设置 PAPERLENS_DATABASE_URL=postgresql+psycopg://user:pass@host/db。

注意：本机没有 Postgres 实例，**未做真实回归**；上线前必须验证迁移、并发写、JSON 查询与 pg_dump 备份。

## 8. 生产检查清单

- [ ] SECRET_KEY 随机且 >=32
- [ ] 关闭开发调试/ reload
- [ ] 限流开启并设置合理值
- [ ] 反向代理 HTTPS
- [ ] 数据目录持久化
- [ ] 定时备份 + 恢复演练
- [ ] 模型 Key 由用户/环境提供，不写入仓库
- [ ] 日志与磁盘空间监控
- [ ] Postgres（若使用）已实机验证

