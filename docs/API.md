# API 参考

所有接口前缀为 `/api`。除注册/登录/健康检查外均需：

```http
Authorization: Bearer <access_token>
```

错误格式：

```json
{ "detail": "可读错误信息" }
```

部分错误返回结构化 detail：

```json
{ "detail": { "code": "duplicate", "message": "资料库中已存在同一篇论文", "paper_id": "..." } }
```

---

## 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register` | `{email, password, display_name}` → token + user + settings |
| POST | `/auth/login` | `{email, password}` → token |
| GET | `/auth/me` | 当前用户与设置 |
| PATCH | `/auth/profile` | `{display_name?, affiliation?, avatar_color?}` |
| POST | `/auth/change-password` | `{current_password, new_password}` |

## 论文

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/papers` | multipart：`file`、`tags`、`collection_id`、`allow_duplicate` |
| GET | `/papers` | `query,status,favorite,tag,collection_id,sort,limit,offset` |
| GET | `/papers/tags` | 标签统计 |
| GET | `/papers/{id}` | 元数据 + 章节 + 计数 |
| PATCH | `/papers/{id}` | 标题/作者/年份/标签/收藏/笔记 |
| DELETE | `/papers/{id}?confirm=true` | 删除论文与文件 |
| POST | `/papers/{id}/reprocess` | 重新解析 |
| GET | `/papers/{id}/file` | 原始 PDF（需鉴权） |
| GET | `/papers/{id}/outline` | 章节 + 切片预览 |
| GET | `/papers/{id}/pages/{n}` | 单页文本与尺寸 |

## 批注

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/annotations?paper_id=&color=&tag=&favorite=` | 列表（默认排除已删除） |
| POST | `/annotations` | `{paper_id,page,color,quote,rects,note,tags}` |
| PATCH | `/annotations/{id}` | 颜色/笔记/标签/收藏 |
| DELETE | `/annotations/{id}` | 软删除，可撤销 |
| POST | `/annotations/{id}/restore` | 恢复 |

## 图表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/figures?paper_id=&saved=&kind=&query=` | 图表列表 |
| GET | `/figures/{id}/image` | 图片（需鉴权） |
| PATCH | `/figures/{id}` | 笔记 / 收藏 |
| POST | `/figures/{id}/explain` | AI 解释（无 Key 返回 409 model_required） |

## 证据（Evidence System）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/evidence` | 筛选：`paper_id, chunk_id, type, verified, source_type, source_id, analysis_id, query, limit, offset` |
| GET | `/evidence/stats` | 总数 / 已核对 / 覆盖论文 / 按类型计数 |
| POST | `/evidence` | 手动创建证据 |
| GET | `/evidence/{id}` | 证据详情 |
| PATCH | `/evidence/{id}` | 修改类型 / 断言 / 置信度 |
| DELETE | `/evidence/{id}` | 删除证据 |
| POST | `/evidence/from-annotation/{id}` | 批注转证据 |
| POST | `/evidence/from-knowledge/{id}` | 知识转证据 |
| POST | `/evidence/backfill` | 回填历史消息/批注/知识 |

创建证据请求：

```json
{
  "paper_id": "...",
  "chunk_id": "...",
  "page": 2,
  "quote": "原文中的一句话",
  "claim": "这条证据支撑的结论",
  "evidence_type": "direct",
  "confidence": 0.9,
  "source_type": "manual",
  "source_id": null,
  "analysis_id": null
}
```

证据类型：`direct / shared / inferred / hypothesis / insufficient / external`。
返回包含 `verified`、`verification_note`、`confidence`、`can_locate`。

```http
POST /api/research/compare
```

响应新增：

```json
{
  "content": "...",
  "citations": [],
  "local": true,
  "analysis_id": "...",
  "evidence_count": 6
}
```

`POST /api/chat/stream` 的 `done` 事件新增 `evidence_count` 与 `evidence_ids`。

---

## 对话与 Agent

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/chat/stream` | SSE 流式回答 |
| GET | `/conversations` | 历史列表 |
| GET | `/conversations/{id}` | 消息与引用 |
| PATCH | `/conversations/{id}` | 标题 / 归档 |
| DELETE | `/conversations/{id}` | 删除 |
| GET | `/agent/runs` | 执行记录 |
| GET | `/agent/runs/{id}` | 步骤详情 |
| POST | `/agent/actions/confirm` | `{tool, args}` 执行待确认写操作 |

`POST /chat/stream` 请求：

```json
{
  "message": "这些论文的实验设计有什么差异？",
  "conversation_id": null,
  "mode": "multi_paper",
  "scope_type": "papers",
  "scope_ids": ["..."],
  "auto_approve_writes": false
}
```

SSE 事件：

| type | 载荷 |
| --- | --- |
| `start` | conversation_id, run_id, provider, scope |
| `step` | step {index, tool, label, status, summary, duration_ms} |
| `delta` | text |
| `action` | {tool, args, label, preview} |
| `notice` | message（降级/警告） |
| `done` | message_id, content, citations, actions |
| `error` | message |

## 研究

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/papers/{id}/summary` | `{mode}` → 总结 + 引用 |
| POST | `/papers/{id}/analysis` | `{mode}`：critical/innovation/limitation/future |
| POST | `/papers/{id}/translate` | `{text?, page?, section_id?, target_language?}` |
| POST | `/papers/{id}/extract` | `{instruction}` |
| POST | `/research/compare` | `{paper_ids, focus, fragments?}` |
| POST | `/research/gap` | `{paper_ids, collection_id?}` |
| POST | `/research/extract` | `{instruction, paper_ids?, collection_id?}` |

## 性能与运维（P9）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/jobs?limit=` | 当前用户解析任务 + 队列统计 |
| GET | `/jobs/stats` | 队列统计 |
| GET | `/jobs/{id}` | 任务详情 |
| POST | `/jobs/{id}/retry` | 失败/取消任务重试 |
| GET | `/ops/metrics` | 队列、RAG 缓存、限流、DB、模型超时指标 |

配置：

- `PAPERLENS_RATE_LIMIT_ENABLED`
- `PAPERLENS_RATE_LIMIT_PER_MINUTE`（开发默认 600）
- `PAPERLENS_REQUEST_TIMEOUT_SECONDS`（默认 300）
- `PAPERLENS_LLM_TIMEOUT_SECONDS`（默认 180）

限流触发返回 429 + Retry-After。

---

## 学术成果（P8）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/artifacts/kinds` | 八类成果元数据 |
| POST | `/artifacts/generate` | 生成 + 自动质检；body: kind/scope |
| GET | `/artifacts` | 历史成果 |
| GET | `/artifacts/{id}` | 成果 + 最新质检 |
| POST | `/artifacts/{id}/check` | 重新质检 |
| POST | `/artifacts/{id}/export` | 导出 md/pdf/docx |
| DELETE | `/artifacts/{id}` | 删除 |

成果响应包含：content、citations、evidence_table、scope_statement、quality_status/score。
质检 issues 的 severity 为 error/warning；error 会把 status 置为 fail。

---

## 知识智能（P7）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/knowledge?query=&cluster=` | 混合检索 + 主题过滤 |
| POST | `/knowledge` | 创建；重复 409；`force=true` 可显式保存 |
| PATCH | `/knowledge/{id}` | 编辑；生成新版本 |
| GET | `/knowledge/duplicates?threshold=` | 相似条目对 |
| GET | `/knowledge/clusters` | 标签聚类 |
| GET | `/knowledge/{id}/versions` | 版本列表 |
| POST | `/knowledge/{id}/versions/{v}/rollback` | 回滚（生成新版本） |
| POST | `/knowledge/{id}/merge` | 合并相似条目 |
| GET | `/knowledge/graph` | 含 tag/method/dataset/question 节点 |

`POST /knowledge` 命中重复时返回 409：

```json
{
  "detail": {
    "code": "duplicate_knowledge",
    "message": "发现相似知识（相似度 92%），未创建新条目。",
    "score": 0.92,
    "candidate": {"id": "...", "title": "..."}
  }
}
```

知识条目新增字段：`auto_tags`、`cluster_key`、`cluster_label`、`version`、`duplicate_of`、`search_score`。

---

## Agent 任务（P6）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/agent/tasks/plan` | 只创建计划，不执行 |
| GET | `/agent/tasks?status=` | 任务列表 |
| GET | `/agent/tasks/{id}` | 任务、步骤、结果消息 |
| PATCH | `/agent/tasks/{id}/plan` | 修改计划（queued/paused） |
| POST | `/agent/tasks/{id}/execute` | SSE 执行 |
| POST | `/agent/tasks/{id}/pause` | 暂停 |
| POST | `/agent/tasks/{id}/resume` | 继续 |
| POST | `/agent/tasks/{id}/cancel` | 取消 |
| POST | `/agent/tasks/{id}/rerun` | 创建重跑任务 |

状态：`queued | running | paused | cancelled | completed | failed`。

SSE 新增事件：

- `plan`：计划与任务 id
- `paused` / `resumed`
- `cancelled`
- `self_check`：引用覆盖、失败步骤、风险
- `done`：增加 `task_id`、`self_check`、`plan`

取消后的任务不会写 assistant message / evidence / usage。

---

## 研究情报（P5）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/intelligence/scope?scope_type=all|collection|project&scope_id=` | 解析范围；返回论文、年份、边界 |
| POST | `/intelligence/overview` | 生成/复用四类报告；body: `{scope_type, scope_id, force}` |
| GET | `/intelligence/reports` | 历史报告，可按 `kind`/`scope_type`/`scope_id` 过滤 |
| GET | `/intelligence/reports/{id}` | 单份报告 |

`scope_type`：

- `all`：全部已解析论文（最多 60 篇）
- `collection`：合集内论文
- `project`：项目内论文
- `papers`：指定论文（API 支持，当前页面用前三种）

响应包含 `scope`：

```json
{
  "type": "all",
  "label": "全部资料库",
  "paper_count": 2,
  "years": [2024],
  "year_min": 2024,
  "year_max": 2024,
  "unknown_years": 0,
  "boundary": "仅基于资料库内论文，不代表全球学术领域",
  "external_data": false
}
```

四类报告：`landscape` / `trends` / `connections` / `opportunities`。
每类都有 `local`、`data`、`citations`；生成式失败会回退本地并在 `note` 说明。

---

## 多论文研究情报（P4）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/research/matrix` | 证据矩阵；body: `{paper_ids, force}` |
| POST | `/research/conflicts` | 观点冲突 + 实验条件可比性 |
| POST | `/research/evolution` | 方法时间线 + 关系（explicit/possible） |
| POST | `/research/gap/validate` | 缺口跨论文证据覆盖；body: `{claim, paper_ids}` |
| GET | `/research/insights` | 研究情报历史，`kind=matrix|conflicts|evolution|gap_validation` |
| GET | `/research/insights/{id}` | 情报详情 |

矩阵响应核心：

```json
{
  "insight_id": "...",
  "rows": [
    {
      "paper_id": "...",
      "title": "...",
      "year": 2024,
      "fields": {
        "research_question": {"text": "...", "quote": "...", "page": 1, "evidence_id": "...", "verified": true},
        "method": {"text": "...", "quote": "...", "page": 2, "verified": true}
      }
    }
  ],
  "dimensions": [{"id": "method", "label": "研究方法"}],
  "local": true,
  "note": "..."
}
```

冲突响应包含 `conflicts`、`comparability`、`profiles`、`local`、`note`。
本地模式 `conflicts` 为空且明确说明“不判定”；不会伪造冲突。

演化响应包含 `timeline`、`relations`、`local`、`note`。
关系的 `status` 为 `explicit|possible|unknown`。

---

## 知识库 / 合集 / 项目

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/collections` | 列表 / 创建 |
| PATCH/DELETE | `/collections/{id}` | 更新 / 删除 |
| POST | `/collections/{id}/papers` | body: `["paper_id"]` |
| DELETE | `/collections/{id}/papers/{paper_id}` | 移除 |
| GET/POST | `/knowledge` | 搜索/筛选 / 创建 |
| PATCH/DELETE | `/knowledge/{id}` | 更新 / 删除 |
| POST | `/knowledge/links` | 创建关联 |
| DELETE | `/knowledge/links/{id}` | 删除关联 |
| GET | `/knowledge/graph` | 图谱节点与边 |
| GET/POST | `/projects` | 列表 / 创建 |
| GET/PATCH/DELETE | `/projects/{id}` | 详情 / 更新 / 删除 |
| POST | `/projects/{id}/items` | 添加条目 |
| DELETE | `/projects/{id}/items/{item_id}` | 移除条目 |
| GET | `/library/stats` | 工作区统计 |

## 导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/exports` | 导出记录 |
| POST | `/exports` | `{kind, format, title, content?, paper_id?, knowledge_ids?, project_id?}` |
| GET | `/exports/{id}/download` | 下载（需鉴权） |
| DELETE | `/exports/{id}` | 删除记录 |

## 设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/PATCH | `/settings` | 偏好 + 模型公开状态 |
| POST | `/settings/model-key` | 测试连接并加密保存 |
| DELETE | `/settings/model-key` | 移除密钥 |
| GET | `/settings/usage` | 使用量 |
| POST | `/settings/data-export` | 全量数据 JSON |
| DELETE | `/settings/account` | 密码 + DELETE 确认后删除账号 |

## 健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 版本、环境、模型提供方、存储路径 |

交互式文档：`/api/docs`（OpenAPI）。