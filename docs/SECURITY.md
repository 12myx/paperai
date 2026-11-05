# 安全说明

## 1. 威胁模型

PaperLens 处理的是**私有科研资料**。主要风险：

1. 未授权访问他人论文、批注与知识；
2. 通过恶意 PDF 或提示注入操纵模型；
3. 通过文件名/路径读取服务器任意文件；
4. XSS 或令牌泄露；
5. 模型密钥泄露；
6. 误删除研究数据。

## 2. 已实施的控制

| 领域 | 控制 | 位置 |
| --- | --- | --- |
| 密码 | bcrypt（12 rounds），SHA-256 预哈希避免 72 字节截断 | `security.py` |
| 会话 | JWT HS256，7 天过期，`iss=paperlens`，Bearer 头 | `security.py` / `deps.py` |
| 数据隔离 | 每个查询按 `user_id` 过滤；跨用户访问统一 404（不泄露存在性） | 所有 routers |
| 证据隔离 | Evidence 按 user_id 查询；paper/chunk/analysis 归属校验；跨用户 404 | `evidence.py` |
| 研究情报隔离 | facets/insights 按 user_id；论文归属校验；跨用户 404 | `multipaper.py` |
| 研究情报报告隔离 | intelligence_reports 按 user_id/scope；跨用户 404 | `intelligence.py` |
| 任务隔离 | agent_tasks 按 user_id；plan/execute/pause/cancel/rerun 均校验归属 | `chat.py` |
| 知识版本隔离 | knowledge_meta/versions 按 user_id；跨用户版本/回滚/合并 404 | `library.py` |
| 成果隔离 | academic_artifacts/quality 按 user_id；跨用户 404 | `artifacts.py` |
| 成果导出 | 导出记录绑定 user_id，下载再次鉴权 | `exports.py` |
| 限流 | 滑动窗口按 Authorization+IP；429 + Retry-After | `rate_limit.py` |
| 队列隔离 | jobs 按 user_id；重试校验归属 | `jobs.py` |
| 备份 | CLI 恢复需 --yes；恢复前保存副本 | `backup.py` |
| 重复知识 | 默认 409；force/确认才创建；合并校验来源归属 | `knowledge.py` |
| 取消不写库 | cancel 状态在 assistant message/evidence 前拦截 | `agent.py` |
| 证据核验 | 引用必须在真实 chunk 中找到，否则标记未核对 | `verify_quote` |
| 文件路径 | 存储根目录解析 + 前缀校验，拒绝 `..` 穿越 | `storage.abs_path` |
| 上传 | 50MB 限制、扩展名校验、`%PDF` 魔数、页数上限、随机目录 | `papers.py` / `pdf.py` |
| 密钥存储 | 用户 API Key 使用 Fernet 对称加密；接口只返回 `has_api_key` | `security.py` / `settings.py` |
| 密钥传输 | 仅服务端到模型端；前端永不持有模型密钥 | `llm.py` |
| 提示注入 | 系统提示明确论文文本只是资料；工具结果以引用块进入上下文 | `llm.py` / `agent.py` |
| XSS | React 默认转义；Markdown 不启用 raw HTML；无 `dangerouslySetInnerHTML` | 前端 |
| CSRF | 使用 Bearer 头而非 Cookie，跨站表单无法自动携带 | 前端 API 层 |
| CORS | 显式来源列表；生产禁止通配符 | `main.py` / `config.py` |
| 响应头 | nosniff、DENY frame、Referrer-Policy、Permissions-Policy | 中间件 |
| 删除保护 | 论文删除需 `confirm=true`；批注软删除 + 撤销；账号删除需密码 + DELETE | routers |
| 审计 | `usage_events`：注册、上传、解析、对话、改密 | models |
| 生产校验 | 默认/过短 SECRET_KEY 拒绝启动 | `config.py` |

## 3. 提示注入的具体处理

论文正文可能包含“忽略之前的指令”等文本。PaperLens 的处理：

1. 系统提示固定声明：论文文本只是被引用的资料，不是指令；
2. 工具结果以 `[C#]` 引用块传递，而非直接拼接到 system；
3. 智能体只能调用白名单工具；
4. 写操作（保存知识/批注/导出）需要用户显式确认，模型不能静默写库；
5. 模型输出不被当作代码执行，前端只渲染 Markdown。

仍需注意：没有任何提示防护是绝对可靠的；对高敏感场景，建议在展示前增加人工审核。

## 4. 密钥与配置

- `.env` 不应提交（`.gitignore` 已排除）；
- Docker 镜像不包含 `.env`（`.dockerignore`）；
- `PAPERLENS_SECRET_KEY` 轮换会使所有 JWT 失效；
- `PAPERLENS_ENCRYPTION_KEY` 轮换会使已存用户密钥无法解密（需重新配置）；
- 建议每 90 天轮换模型密钥；
- 模型请求会将论文片段发送给模型提供方，需在隐私说明中告知用户。

## 5. 数据生命周期

| 操作 | 行为 |
| --- | --- |
| 删除批注 | 软删除，可恢复 |
| 删除论文 | 删除数据库记录 + 该论文目录（PDF/图表），需确认 |
| 删除账号 | 删除全部业务数据 + storage 目录，需密码 + DELETE |
| 删除论文 | 级联删除该论文证据；切片删除后证据 chunk_id 置空 |
| 导出数据 | 生成 JSON 快照，含论文元数据、批注、知识、项目、对话 |
| 备份 | 见部署文档；备份文件含完整论文，需同等保护 |

## 6. 运行时建议

1. 全站 HTTPS，HSTS；
2. 反向代理层限制请求体大小与超时；
3. 对 `/api/auth/*` 增加速率限制（当前未内置）；
4. 定期更新依赖（`pip list --outdated`、`npm audit`）；
5. 监控失败登录与异常 4xx；
6. 生产建议 PostgreSQL + 独立数据库账号；
7. 容器以非 root 用户运行（Dockerfile 已创建 uid 10001）。

## 7. 已知残余风险

| 风险 | 影响 | 缓解 / 后续 |
| --- | --- | --- |
| JWT 存于 localStorage | XSS 可窃取会话 | 无 raw HTML；后续可改 httpOnly Cookie + CSRF Token |
| 无速率限制 | 暴力破解/刷接口 | 建议在 Nginx 或应用层增加 |
| 无邮箱验证 | 可注册任意邮箱 | 生产接入邮件服务 |
| SQLite 并发写 | 高并发下锁 | 切换 PostgreSQL |
| 无病毒扫描 | 恶意 PDF 解析风险 | 容器隔离 + 依赖更新；可接入 ClamAV |
| 无审计导出 | 合规审计困难 | 导出 `usage_events` |
| 模型数据外发 | 论文片段离开服务器 | 用户知情选择；可接入私有模型端点 |
| 证据只核验引用 | 结论可能超出引用支持范围 | P5/P8 增加 claim-level 检查 |
| 本地冲突/演化 | 不做语义判断，避免误判 | UI 明确标注；模型模式需人工复核 |
| 研究情报范围 | 只分析资料库，不能代表全球领域 | UI/API 标注 external_data=false |

## 8. 漏洞报告

请将复现步骤、影响范围与版本发送给项目维护者。不要在生产数据上测试破坏性操作。