# 性能与稳定 · P9

> 2026-11-04 · 队列、增量索引缓存、限流、超时/重试、备份恢复
> 原则：只报告真实测得的数字；没有实例的 Postgres 明确标为未验证。

## 1. 队列

- 新增 processing_jobs 表：queued / running / retrying / completed / failed
- 单进程单 worker（SQLite 单写），启动时恢复 queued/running/retrying 任务
- 上传与重新解析改为入队，不再依赖 FastAPI BackgroundTasks
- 每次尝试更新 attempts；最多 3 次；指数退避 2/4 秒
- 进度：阶段 + 百分比；图书馆顶部显示解析队列

实测：

    completed 1 / attempts 1 / progress 100
    workers 1 / active 0

## 2. 增量索引缓存

- 检索仍使用 BM25 + 字符 trigram 的 HybridIndex
- 新增按论文的 Document 缓存，key 含 paper.updated_at + title + chunk_count
- 论文重解析只失效该论文的文档缓存；其他论文文档复用
- 索引 scope 缓存 90 秒；增删论文使用 invalidate_paper
- /ops/metrics 暴露 index_builds / document_hits / document_misses

5k chunks 合成基准：

    build_ms: 10424.78（一次性构建）
    queries: 32
    p50: 36.81 ms
    p95: 41.62 ms（目标 <300ms）
    max: 42.06 ms

50 篇论文列表查询（合成 SQLite）：

    7.28 ms（目标 <500ms）

注意：5k chunks 构建约 10 秒，必须依赖缓存；每次重建不可接受。

## 3. 限流

- 进程内滑动窗口，按 Authorization + IP 哈希分桶
- 开发默认 600 请求/分钟；生产可用 PAPERLENS_RATE_LIMIT_PER_MINUTE 调整
- 429 + Retry-After + X-RateLimit-Remaining
- 并发测试：limit=10，50 个并发 hit，恰好 10 个通过

限制：多进程部署需要 Redis 共享桶。

## 4. 超时与重试

- 请求级：300 秒超时，返回 504
- 模型连接：180 秒超时
- 模型 429/5xx：最多 3 次尝试，指数退避，尊重 Retry-After
- 401/403 不重试，直接提示 Key 无效

## 5. 备份 / 恢复

CLI：

    python scripts/backup.py create
    python scripts/backup.py inspect backups/xxx.zip
    python scripts/backup.py restore backups/xxx.zip --yes

实测备份：

    database_bytes: 7,233,536
    storage_files: 108
    zip bytes: 11,963,440
    manifest sha256: e186464e...
    inspect entries: 110

恢复演练在 pytest 临时目录完成：checksum 校验、SQLite 数据、storage 文件均恢复。
恢复会先保存 .pre-restore-* 副本；不会自动删除。

## 6. 并发与事务

- SQLite 单写；队列单 worker，避免并发解析写锁
- 进度更新与解析写入解耦：进度写失败只跳过，不阻塞解析
- pytest 覆盖：并发限流、队列重解析、缓存命中、备份恢复
- 模型重试未做真实 5xx 注入（无可用故障端点）

## 7. PostgreSQL

当前机器没有 psql、Docker 或 Postgres 服务。

因此：

- 没有声称“Postgres 已实机验证”
- 仅保留 SQLAlchemy 模型兼容与 DATABASE_URL 切换路径
- 部署前必须做：迁移、并发写、JSON/索引、备份（pg_dump）回归

## 8. 指标与限制

| 项 | 结果 |
| --- | --- |
| 5k chunks p95 | 41.62 ms |
| 50 paper list | 7.28 ms |
| 队列恢复 | 启动时重新入队 |
| 限流 | 429 真实生效 |
| 备份校验 | sha256 通过 |
| Postgres | 未验证 |
| 多进程队列 | 未实现 |
| 分布式限流 | 未实现 |

## 9. 下一步

P10 / 收尾：部署、CI、演示材料与最终提交。
