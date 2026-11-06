> **历史基线（升级前）**：本报告记录 A0 修复前的 7 个失败项；修复后的复测见 [V3.2 产品升级报告](../docs/V3.2_PRODUCT_UPGRADE.md)。

# PaperLens AI 全流程测试报告

> 测试日期：2026-11-06
> 代码版本：`8c8eac6`
> 测试地址：http://127.0.0.1:8000
> 原则：**只测试，不修改业务代码**。所有失败原样记录。

## 1. 结论

| 测试层 | 结果 |
| --- | --- |
| 后端 pytest | **71 / 71 通过** |
| 浏览器 E2E | **38 / 38 通过** |
| 独立 API 全流程 | **84 / 88 通过，4 失败** |
| 额外边界/深链接/账号清理 | **3 失败** |
| 备份创建/检查/恢复 | 通过 |
| Docker / Railway / PostgreSQL / 真实 LLM | **未测试（本机条件不具备）** |

共发现 **7 个独立缺陷**。当前版本可以完成大部分演示流程，但存在 1 个直接 500、1 个隐私残留、1 个证据误判、1 个队列重试死锁，**不建议直接作为公开生产版本**。

---

## 2. 测试环境

- 服务：本机 `development` 模式，`http://127.0.0.1:8000`
- 数据库：`backend/data/paperlens.db`
- 测试账号：隔离的 `flowtest-...@example.com`，测试结束已调用删除账号接口
- 主资料库：`qa@paperlens.ai`，仅用于下载真实样本文档
- 测试前备份：`backups/pre-test.zip`
  - 12,046,533 bytes
  - database sha256: `599aced1611b30ce838f827b17a221984cefe28bea2182946de4cc5e9e3a194c`
  - storage files: 110
- 数据库完整性：`PRAGMA integrity_check = ok`

测试命令：

```text
python -m pytest tests -q -p no:cacheprovider
node run.mjs
python %TEMP%\paperlens_flow_test.py
python %TEMP%\paperlens_deeplink_test.cjs
python %TEMP%\paperlens_delete_test.py
python %TEMP%\paperlens_prefix_test3.py
```

---

## 3. 失败项（按严重度）

### F1. 更新论文信息直接 500（严重）

**接口：**

```http
PATCH /api/papers/{paper_id}
{"favorite":true,"note":"flow note","tags":["flow","updated"]}
```

**实际：**

```text
HTTP 500
{"detail":"服务器内部错误，请稍后重试"}
```

**服务端堆栈：**

```text
File ".../backend/app/routers/papers.py", line 198, in update_paper
    invalidate(user.id)
NameError: name 'invalidate' is not defined
```

**原因：** `papers.py` 只导入了 `invalidate_paper`，但 `update_paper()` 调用了 `invalidate()`。
**影响：** 收藏、笔记、标签等论文编辑功能全部返回 500；由于 `db.commit()` 在异常前已经执行，数据可能实际写入，但前端仍显示失败。
**建议：** 补充导入或改为 `invalidate_paper(user.id, paper.id)`。
**本次未修改代码。**

---

### F2. 队列失败任务手动重试后永远停在 queued（高）

**复现：**

1. 上传一个仅以 `%PDF` 开头、实际损坏的 PDF；
2. 任务重试 3 次后进入 `failed`；
3. 调用 `POST /api/jobs/{job_id}/retry`，返回 200；
4. 等待后再次查询任务。

**实际：**

```json
{
  "status": "queued",
  "attempts": 3,
  "max_attempts": 3
}
```

任务不会进入 running，也不会重新执行。

**原因：**

- `retry()` 重置了 status/progress/error，但没有重置 `attempts`；
- `_run()` 使用 `range(attempts + 1, max_attempts + 1)`；
- 当 `attempts == max_attempts` 时循环为空，直接返回。

**影响：** 用户点击“重试”没有效果；服务重启恢复时同样可能卡死。
**建议：** retry 和 `_recover` 都把 `attempts` 重置为 0，或改为从 1 开始的循环。
**本次未修改代码。**

---

### F3. 空白/扫描版 PDF 被标记为 ready，但切片数为 0（高）

**测试：** 用 ReportLab 生成一个合法但无文本的空白 PDF，上传到新账号。

**实际：**

```json
{
  "status": "ready",
  "chunks_count": 0
}
```

接口上传和解析都返回成功，但论文没有任何可检索文本。

**影响：** 用户看到“已解析”，实际问答永远没有证据；扫描版论文会静默失效。
**建议：** `len(chunks) == 0` 时标记 `failed` 或 `ready_with_warning`，并在 UI 显示“未提取到文本，可能需要 OCR”。
**本次未修改代码。**

---

### F4. 删除导出记录后磁盘文件仍然存在（中）

**测试：**

1. 创建导出 `flow-delete-check.md`；
2. 调用 `DELETE /api/exports/{id}`，返回 200；
3. 检查数据库记录的 storage 路径。

**实际：**

```text
文件仍存在：
backend/data/storage/users/<user>/exports/flow-delete-check.md
```

**影响：** 用户删除导出后文件仍留在磁盘；长期使用会造成存储泄漏，也不符合“删除”语义。
**建议：** 删除 ExportRecord 前/后调用 storage 删除对应文件；artifact 删除时同步清理其导出。
**本次未修改代码。**

---

### F5. 历史对话深链接打开为空（高）

**测试：**

- API 确认会话 `201b4b4aabc343a886239462238da6c0` 有 2 条消息；
- 浏览器登录后访问 `/app?conversation=201b4b4aabc343a886239462238da6c0`；
- 等待 3.5 秒后统计消息节点。

**实际：**

```text
DEEP_LINK messages=0 errors=0
```

页面没有控制台错误，但历史消息没有加载。

**原因：**

- `useChat` 用 URL 的 conversation id 初始化 `conversationId`；
- Home 的加载 effect 判断 `initialConversation === conversationId` 后直接 return；
- 首次打开时两者天然相等，因此永远不会调用 `loadConversation()`。

**影响：** 从 History 点击任何历史对话都看到空页面。
**建议：** 用独立的“已加载”标记；初始化时显式加载一次。
**本次未修改代码。**

---

### F6. 删除账号后仍残留多张个人数据表（高）

**测试：**

1. 创建隔离账号；
2. 生成任务、成果、研究分析、研究情报、坏 PDF 任务；
3. 调用 `DELETE /api/settings/account`，返回 200；
4. 再次登录返回 401；
5. 直接查询数据库。

**实际残留：**

```json
{
  "agent_tasks": 4,
  "academic_artifacts": 1,
  "artifact_quality_reports": 2,
  "research_analyses": 6,
  "intelligence_reports": 4,
  "processing_jobs": 4
}
```

**影响：** 用户以为账号已删除，但任务、成果、分析、报告、队列任务仍保存在数据库中。
**建议：** 统一清理所有用户数据表，或补外键 `ON DELETE CASCADE`；增加逐表断言测试。
**本次未修改代码。**

---

### F7. 证据“前缀匹配”会把伪造后缀标记为已核对（高）

**测试：**

- 取 QA 资料库中最长 chunk（1136 字符）；
- 取规范化文本前 90 字符；
- 拼接伪造后缀“这是伪造的后半段内容。”；
- 通过 `POST /api/evidence` 创建证据。

**实际：**

```json
{
  "status": 201,
  "verified": true,
  "verification_note": "前缀匹配"
}
```

**影响：** 只要前 90 字符正确，后半段可以完全伪造，仍显示“已核对原文”。
**建议：** 删除前缀捷径；整段匹配或高覆盖率句子匹配才通过；部分匹配标记 `partial`。
**本次未修改代码。**

---

## 4. 通过项矩阵

| 模块 | 测试内容 | 结果 |
| --- | --- | --- |
| 健康检查 | `GET /api/health` | 通过 |
| 认证 | 注册、登录、`/me`、资料更新、修改密码、重新登录 | 通过 |
| 账号删除 | 删除接口 200、旧 token/登录失效 | 接口通过；**F6 数据残留失败** |
| 论文 | 上传、解析、重复 409、允许重复、详情、PDF、outline、页码文本、搜索、标签 | 通过 |
| 论文编辑 | 收藏/笔记/标签 PATCH | **F1 500** |
| 批注 | 创建、列表、更新、软删除、恢复 | 通过 |
| 证据 | 批注转证据、直接创建、列表、统计、更新、删除、backfill | 通过 |
| 证据校验 | 伪造后缀前缀测试 | **F7 失败** |
| 研究 | 总结、批判性分析、自定义提取、翻译需模型 409 | 通过 |
| 多论文 | 对比、研究缺口、片段对比 | 通过 |
| 对话 | SSE 完成、4 条引用、会话详情 2 条消息 | 通过 |
| 历史深链接 | `/app?conversation=...` | **F5 0 条消息** |
| 知识库 | 创建、重复 409、force、列表、hybrid search、版本、回滚、合并、聚类、重复对、图谱 | 通过 |
| 合集 | 创建、加论文、列表、移除 | 通过 |
| 项目 | 创建、加条目、详情、删除条目 | 通过 |
| 图表 | 列表、更新 note/saved、鉴权图片加载、解释需模型 409 | 通过 |
| 导出 | 创建、下载、删除 | 接口通过；**F4 文件残留** |
| 学术成果 | 8 种类型、生成、列表、质检、Markdown 导出 | 通过 |
| 研究情报 | scope、四类 overview、reports 列表 | 通过 |
| Agent | 计划、修改计划、执行、任务详情、任务列表、取消、重跑 | 通过 |
| 队列 | 失败 3 次、列表、stats | 通过；**F2 重试死锁** |
| 运维 | `/api/ops/metrics` | 通过 |
| 备份 | 创建、inspect、临时目录恢复、checksum | 通过 |
| 前端 E2E | 38 步、0 console/page error | 通过 |
| 移动端/深色 | QA 第 36、38 步 | 通过 |

---

## 5. 未测试 / 受条件限制

以下项目**没有**在本轮通过真实环境验证，不能写成“已通过”：

1. **Docker 构建/运行**：本机没有 Docker。
2. **Railway / 云平台部署**：没有可用的 Railway 项目。
3. **PostgreSQL**：本机没有实例。
4. **真实生成式模型**：没有可用的 DeepSeek Key 做真实流式生成。
5. **翻译与图表解释**：本地模式按预期返回 409，未测试真实模型输出。
6. **SSRF**：只做了代码审计，没有对内部地址发起攻击请求。
7. **400 页 / 50MB 压力**：只测了普通样本文档；大 PDF 内存与耗时未压测。
8. **多用户并发**：只测单用户顺序流程；并发注册、facet/evidence 唯一约束竞争未实测。
9. **实时暂停/继续**：任务执行过快，暂停请求未能在流结束前稳定插入；后端已有暂停/继续状态测试，但没有真实流式暂停截图。
10. **公网部署后的 Cookie/CORS/HTTPS**：未验证。

---

## 6. 测试数据与清理

- 测试前备份：`backups/pre-test.zip`，可用于恢复测试前数据。
- QA 账号的 E2E 数据被本轮测试新增（批注、知识、任务、成果等），这是 QA 数据，不影响源代码。
- 隔离账号已调用删除接口，但按 F6，数据库中仍有残留孤儿数据。
- **没有修改任何业务代码、配置或迁移文件。** 本报告是唯一新增文件。

如需恢复测试前数据，请先停止服务，再运行：

```text
cd backend
python scripts/backup.py restore ..\backups\pre-test.zip --yes
```

不要在服务运行时直接恢复。

---

## 7. 建议修复顺序

1. **F1**：补上 `invalidate` 或改调用 —— 一行级修复，但影响所有论文编辑。
2. **F6**：统一账号删除清理，避免隐私残留。
3. **F2**：重置 attempts，修复队列重试/重启恢复。
4. **F7**：收紧证据校验，避免“已核对”误判。
5. **F5**：修复历史对话初始加载。
6. **F3**：空白 PDF 标记失败/警告。
7. **F4**：删除导出时同步删除文件。
8. 再处理本轮未覆盖的 Docker/Railway/Postgres/并发。

---

## 8. 最终判定

- **演示流程**：大部分可通过；E2E 38 步通过。
- **生产可用**：**不通过**，主要 blocked by F1、F2、F3、F5、F6、F7。
- **部署建议**：在修复以上失败项之前，不要公开给真实用户使用；可以继续做本地/内测演示。