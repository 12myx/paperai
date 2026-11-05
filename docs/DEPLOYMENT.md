# 部署与运维

## 1. 环境要求

| 项 | 开发 | 生产 |
| --- | --- | --- |
| Python | 3.11+ | 3.12（镜像已包含） |
| Node.js | 20+ | 仅构建阶段需要 |
| 内存 | 2GB | 2–4GB |
| 磁盘 | — | PDF 与图表存储；按用户量预留 |
| 反向代理 | 无 | Nginx + TLS |

## 2. 本地开发

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
python run.py                     # :8000

cd ../frontend
npm install
npm run dev                       # :5173，代理 /api 到 :8000
```

## 3. 单机生产构建（不使用 Docker）

```bash
cd frontend && npm ci && npm run build
cd ../backend
export PAPERLENS_ENVIRONMENT=production
export PAPERLENS_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export PAPERLENS_DATABASE_URL="sqlite:///./data/paperlens.db"
export PAPERLENS_STORAGE_DIR="./data/storage"
export PAPERLENS_CORS_ORIGINS="https://paperlens.example.com"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers
```

> FastAPI 会自动托管 `frontend/dist`。访问 `http://127.0.0.1:8000` 即为完整产品。
> 生产环境如果 `PAPERLENS_SECRET_KEY` 仍为默认值或少于 32 字符，应用会拒绝启动。

## 4. Docker

```bash
cp .env.example .env
# 编辑 .env：
#   PAPERLENS_SECRET_KEY=<48 位随机值>
#   PAPERLENS_CORS_ORIGINS=https://your-domain
#   DEEPSEEK_API_KEY=<可选>
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/health
```

数据卷 `paperlens-data` 挂载到 `/app/data`，包含 SQLite 与上传文件。**删除容器不会删除数据；执行 `docker compose down -v` 会。**

### 使用 PostgreSQL

```bash
export POSTGRES_PASSWORD=strong-password
docker compose --profile postgres up -d
```

在 `.env` 中设置：

```
PAPERLENS_DATABASE_URL=postgresql+psycopg://paperlens:strong-password@db:5432/paperlens
```

然后 `docker compose up -d paperlens`。应用启动时自动建表（无 Alembic 迁移；后续 schema 变更需要迁移工具）。

## 5. 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `PAPERLENS_SECRET_KEY` | 生产必填 | JWT 签名，≥32 字符；泄露需立即轮换（所有会话失效） |
| `PAPERLENS_ENVIRONMENT` | 建议 | `production` 启用安全校验 |
| `PAPERLENS_DATABASE_URL` | 否 | 默认 SQLite；支持 PostgreSQL |
| `PAPERLENS_STORAGE_DIR` | 否 | 文件目录，容器内为 `/app/data/storage` |
| `PAPERLENS_CORS_ORIGINS` | 生产建议 | 逗号分隔的显式来源；生产禁止 `*` |
| `PAPERLENS_MAX_UPLOAD_MB` | 否 | 默认 50 |
| `PAPERLENS_MAX_PDF_PAGES` | 否 | 默认 400 |
| `DEEPSEEK_API_KEY` | 否 | 服务端默认模型密钥 |
| `PAPERLENS_DEEPSEEK_BASE_URL` | 否 | 任意 OpenAI 兼容端点 |
| `PAPERLENS_DEEPSEEK_MODEL` | 否 | 默认 `deepseek-chat` |
| `PAPERLENS_LLM_TIMEOUT_SECONDS` | 否 | 默认 180 |
| `PAPERLENS_ENCRYPTION_KEY` | 否 | 用户密钥加密；默认派生自 SECRET_KEY。**修改后已存密钥无法解密** |

## 6. Nginx + TLS

参考 [deploy/nginx.conf](../deploy/nginx.conf)。关键点：

- `client_max_body_size 55m`（与上传限制匹配）；
- `proxy_buffering off`（SSE 流式输出必须）；
- `proxy_read_timeout 300s`（长论文分析）；
- TLS、HSTS 与安全响应头。

```bash
certbot --nginx -d paperlens.example.com
nginx -t && systemctl reload nginx
```

## 7. 备份

### SQLite

```bash
cd backend
python scripts/backup.py --out /var/backups/paperlens
```

生成 `paperlens-YYYYmmdd-HHMMSS.zip`，包含一致的数据库快照（sqlite backup API）与整个 storage 目录。

建议 cron：

```cron
0 3 * * * cd /opt/paperlens/backend && /opt/paperlens/.venv/bin/python scripts/backup.py --out /var/backups/paperlens >> /var/log/paperlens-backup.log 2>&1
```

### PostgreSQL

```bash
pg_dump "$PAPERLENS_DATABASE_URL" -Fc -f /var/backups/paperlens-$(date +%F).dump
tar czf /var/backups/paperlens-storage-$(date +%F).tar.gz -C /app/data storage
```

### 恢复

1. 停止应用；
2. 解压备份，替换 `data/paperlens.db` 与 `data/storage`；
3. 启动应用，检查 `/api/health` 与登录；
4. 抽查论文阅读、批注与导出。

## 8. 升级

```bash
git pull
docker compose build --pull
docker compose up -d
docker compose logs -f --tail=100 paperlens
```

升级前先备份。当前版本不使用迁移框架；P3/P4/P5/P6 新增的 `evidence`、`research_analyses`、`paper_facets`、`research_insights`、`intelligence_reports`、`agent_tasks`、`academic_artifacts`、`artifact_quality_reports`、`processing_jobs` 表会由 `create_all` 自动创建，不修改既有列。若未来出现列变更，需要手工迁移或引入 Alembic。

## 9. 监控与日志

- 健康检查：`GET /api/health`（Docker healthcheck 已配置）。
- 应用日志：`docker compose logs -f paperlens`，包含解析失败与未处理异常堆栈。
- 解析日志：`paperlens.processing`。
- 使用事件：`usage_events` 表（注册、上传、解析、对话、改密）。
- 建议接入：Uptime Kuma / Prometheus node exporter / 日志聚合。

## 10. 故障排查

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 上传返回 413 | 超过限制 | 调整 `PAPERLENS_MAX_UPLOAD_MB` 与 Nginx `client_max_body_size` |
| 论文一直 processing | 大文件解析慢或后台异常 | 查看日志；调用 `/reprocess`；检查内存 |
| 解析失败“受密码保护” | 加密 PDF | 需要先解密 |
| 回答无引用 | 资料库为空或范围过窄 | 上传论文、扩大研究范围 |
| 翻译 409 `model_required` | 未配置模型 | 设置中配置 DeepSeek Key |
| 模型 401 | Key 无效 | 重新测试连接 |
| SSE 一次性出现 | 代理缓冲 | Nginx 关闭 `proxy_buffering` |
| 前端模块 MIME 错误 | Windows 注册表把 .mjs 映射为 text/plain | 已内置 mimetypes 修正；确认使用当前版本 |
| `database is locked` | SQLite 并发写 | 降低 worker 数或切换 PostgreSQL |
| 生产启动失败提示 SECRET_KEY | 安全校验 | 设置 ≥32 字符随机密钥 |

## 11. 上线检查清单

- [ ] `PAPERLENS_SECRET_KEY` 已设置为随机值且未提交到仓库
- [ ] `.env` 权限 600，未被镜像/仓库包含
- [ ] 域名与 TLS 生效，HTTP 强制跳转
- [ ] `PAPERLENS_CORS_ORIGINS` 为实际域名，非通配符
- [ ] 反向代理 SSE 未缓冲，上传大小匹配
- [ ] 数据卷持久化，备份任务已配置并演练恢复
- [ ] `/api/health` 监控接入
- [ ] 至少一个账号完成上传→阅读→批注→导出全流程
- [ ] 若配置模型：密钥测试通过，生成式总结与翻译各验证一次
- [ ] 隐私说明与数据删除流程已告知用户

## P9 运行注意事项

- 解析队列是单进程单 worker；不要在同一 SQLite 上启动多个写入实例。
- 生产多实例请把处理队列迁移到 Redis/Celery，并让限流使用共享存储。
- 备份：`python scripts/backup.py create`；恢复会替换数据库与 storage，必须 `--yes`。
- Postgres 需要 `DATABASE_URL=postgresql+psycopg://...`，并自行运行备份（pg_dump）；当前开发机没有 Postgres 实例，未做真实回归。
