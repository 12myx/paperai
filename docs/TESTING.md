# 测试记录

> 最近执行：2026-11-06（V3.2 / A0 + A5 + A6 + UX） · Windows 11 · Python 3.12.2 · Node.js 24.15 · Chrome（Playwright channel=chrome）

## 1. 测试分层

| 层 | 工具 | 覆盖 |
| --- | --- | --- |
| 后端 API | pytest + Starlette TestClient | 认证、上传、解析、检索、批注、知识、导出、证据、多论文情报、研究情报、Agent 任务、隔离、确认式写操作 |
| 前端 | TypeScript 严格模式 + Vite build | 类型、构建、CSS |
| 浏览器 E2E | Playwright（系统 Chrome） | 真实 UI 流程、PDF 渲染、文字选择、下载、移动端 |
| 生产配置 | 手工脚本 | SECRET_KEY 强制校验、SPA 托管、无效 Key 拒绝、密钥不泄露 |

## 2. 执行命令

```bash
# 1) 后端
cd backend
python -m pytest tests -q

# 2) 前端
cd frontend
npm run build

# 3) 启动服务后运行浏览器验收
cd backend && python run.py          # 终端 A
cd qa && npm install && node run.mjs # 终端 B
```

## 3. 结果摘要

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | **80 passed**，0 failed |
| 前端构建 | **通过**（tsc + vite，无类型错误） |
| 浏览器 E2E | **38 个步骤全部通过**，0 console/page error；独立 UX 检查通过 |
| 生产配置检查 | 默认密钥拒绝启动；SPA 200；无效模型 Key 返回 400；设置接口不泄露密钥 |

构建体积（gzip）：JS ≈ 374 KB，CSS ≈ 32 KB，pdf.worker 1.38 MB（独立 chunk）。

## 4. 后端测试清单（80）

| 测试 | 验证点 |
| --- | --- |
| test_health | 健康检查 |
| test_registration_login_and_profile | 注册、登录、错误密码、未授权、资料更新 |
| test_paper_parsing_extracts_structure | 章节、摘要、切片数量 |
| test_duplicate_detection | SHA-256 重复检测（409） |
| test_pdf_upload_validation | 非 PDF 拒绝、扩展名校验 |
| test_pdf_download_and_outline | 原文件下载、目录、单页文本 |
| test_chat_stream_is_grounded | SSE 事件、引用、消息与 Agent 步骤持久化 |
| test_annotations_persist_and_restore | 创建、筛选、更新、软删除、恢复 |
| test_summary_local_mode | 本地抽取模式与引用 |
| test_translation_requires_model | 无模型时返回 409 model_required |
| test_compare_and_gap_local | 对比矩阵、缺口分析 |
| test_fragment_comparison | 自选片段对比（文本） |
| test_knowledge_library_and_graph | 知识 CRUD、搜索、图谱节点/边 |
| test_collections_and_projects | 合集、项目、条目、进度 |
| test_export_all_formats | md/txt/json/csv/pdf/docx 六种真实文件 |
| test_user_isolation | 跨账号 404（论文/文件/批注/目录） |
| test_agent_write_action_requires_confirmation | 写操作 pending → 确认 → 落库 |
| test_settings_and_model_status | 设置、模型状态、用量、数据导出 |
| test_figures_extracted | 图表提取、鉴权图片、笔记/收藏、越权 404 |
| test_conversation_history | 对话保存、列表、删除 |
| test_tag_filter | 标签筛选与统计 |
| test_critical_analysis_local_mode | 批判性评估（本地模式证据） |
| test_chunk_level_fragment_comparison | chunk_id 片段对比 |
| test_export_knowledge_items | 知识库导出内容校验 |
| test_delete_requires_confirmation | 删除必须 confirm=true |
| test_account_deletion_removes_data | 账号删除（错误确认 400、正确删除、会话失效） |
| test_create_evidence_and_verify | 证据创建、切片定位、原文核验 |
| test_unverifiable_quote_is_marked | 不匹配引用标记 unverified |
| test_evidence_type_validation_and_insufficient | 类型校验、证据不足 |
| test_evidence_user_isolation | 证据跨用户 404 |
| test_chat_harvests_evidence | 对话回答自动沉淀证据 |
| test_summary_persists_analysis_and_evidence | 分析落库 + 证据关联 |
| test_compare_persists_analysis | 多论文对比落库 |
| test_annotation_to_evidence | 批注转证据 |
| test_backfill_and_stats | 历史回填与统计 |
| test_evidence_filters | 证据类型/核验筛选 |
| test_matrix_builds_facets_and_evidence | 六维矩阵、facets、证据 |
| test_conflicts_local_does_not_invent_conflicts | 本地模式不编造冲突 |
| test_evolution_local_only_uses_real_years | 演化时间线只用真实年份 |
| test_gap_validation_returns_evidence_coverage | 缺口跨论文证据覆盖 |
| test_insights_are_queryable | 研究情报持久化与查询 |
| test_matrix_isolation | 跨用户情报隔离 |
| test_matrix_requires_at_least_one_paper | 空论文校验 |
| test_scope_all | 研究情报范围解析与边界 |
| test_overview_builds_four_reports | 全景/趋势/关联/机会 |
| test_overview_cache_and_force | 报告缓存与强制刷新 |
| test_project_scope | 项目范围研究情报 |
| test_intelligence_isolation | 研究情报跨用户隔离 |
| test_reports_listing | 报告列表过滤 |
| test_plan_preview_and_update | 计划预览、任务 queued、用户修改计划 |
| test_execute_task_and_self_check | 执行、SSE、自检、结果落库 |
| test_pause_resume_cancel_without_stream | 暂停/继续/取消状态机 |
| test_task_isolation_and_rerun | 任务隔离、重跑创建新任务 |
| test_task_listing | 任务中心列表 |
| test_auto_tags_and_version_one | 自动标签、v1 |
| test_duplicate_blocks_then_force_creates | 重复 409、force |
| test_versions_and_rollback | 版本/回滚 |
| test_hybrid_search_and_clusters | 混合检索、聚类 |
| test_graph_has_tag_and_concept_nodes | 图谱 tag/概念节点 |
| test_knowledge_isolation | 知识版本隔离 |
| test_merge_similar_knowledge | 合并相似条目 |
| test_generate_every_artifact_kind | 八类成果 + 无 error 质检 |
| test_quality_rerun_and_fake_citation | 伪造引用被质检捕获 |
| test_artifact_export_formats | MD/PDF/DOCX 真实下载 |
| test_artifact_isolation | 成果跨用户隔离 |
| test_paper_metadata_update | 论文收藏/笔记/标签更新 |
| test_blank_pdf_is_not_ready | 空白/扫描 PDF 不假 ready |
| test_export_delete_removes_file | 删除导出同步删文件 |
| test_prefix_with_fabricated_suffix_is_not_verified | 伪造证据后缀不通过 |
| test_retry_exhausted_job_reprocesses | attempts 用尽后重试真正执行 |
| test_changed_paper_invalidates_cache | 论文变化使 RI 缓存失效 |
| test_interrupted_task_is_marked_failed_on_recovery | 重启后 running 任务恢复 |
| test_tool_runner_rejects_paper_outside_scope | 工具不能越出选择范围 |
| test_missing_dataset_is_not_comparable | 未提及数据集不判可比 |
| test_queue_processes_reprocess_and_reports | 持久队列、进度、恢复路径 |
| test_rate_limit_returns_429 | 限流 429 + Retry-After |
| test_incremental_cache_stats | 按论文缓存命中 |
| test_ops_metrics | 队列/缓存/限流/DB 指标 |
| test_backup_create_inspect_restore | 备份校验与恢复 |
| test_rate_limiter_concurrency | 并发限流恰好通过 |

## 5. 浏览器 E2E 步骤（38）

1. 落地页渲染
2. 登录（含首页问候与最近论文）
3. 提问 → 流式回答 → 引用卡片 → Agent 时间线
4. 对话回答“证据视图” → 证据抽屉、核验状态
5. 论文库卡片
6. 打开 PDF → canvas → 持久化高亮 → 目录
7. 真实文本选择 → 5 色高亮 → 保存
8. 整页刷新 → 高亮恢复
9. 批注“加入证据库” → 抽屉
10. 阅读器总结
11. 总结“证据” → 抽屉
12. 批判性评估
13. 导出 DOCX 并真实下载（38,012 bytes）
14. 多论文对比 + 来源
15. 证据矩阵（2 篇 × 6 维）
16. 观点冲突（本地模式不编造）
17. 方法演化时间线
18. 研究缺口报告
19. 缺口跨论文验证
20. 自选片段对比（两个 chunk）
21. 知识库 + 图谱节点
22. 知识智能（自动标签/去重/检索/版本/聚类/图谱）
23. 证据库列表 + 类型筛选
24. 研究情报全景 + 数据边界
25. 研究趋势（真实年份）
26. 知识关联图 + 边依据
27. 研究机会（启发式标注）
28. Agent 计划预览 → 调整 → 执行
29. 任务中心（计划/自检/进度）
30. 取消计划（不生成回答）
31. 学术成果：文献综述 + 实验设计 + 证据表 + 质检 + MD 导出
32. 图表页
33. 项目详情
34. 历史记录
35. 设置 / AI 模型配置
36. 深色主题
37. 写操作确认卡片 → 执行
38. 移动端（390×844）首页、抽屉导航、论文库

> 第 7、8 步使用真实 `Range` 选择文本并触发前端 mouseup 逻辑，不是直接调用 API。
> 第 4、9、11 步 Evidence；第 15–19 步 P4；第 22 步 P7；第 24–27 步 P5；第 28–30 步 P6；第 31 步 P8。数据会随测试递增。

### 证据覆盖率审计

```bash
cd backend
python scripts/audit_evidence.py qa@paperlens.ai
```

最近结果：

```text
evidence total: 1127 | verified: 1125 | unverified: 2
assistant messages: 82 | with citations: 81 | missing evidence: 0
analyses: 146 | with citations: 146 | missing evidence: 0
citation coverage: 100.0%
```

> 1 条未核对是批注引用改了原文标点；系统明确标记，不视为事实。

截图位于 `qa/screenshots/`，精选图已复制到 `docs/screenshots/`。

## 6. 生产配置检查

| 检查 | 结果 |
| --- | --- |
| `PAPERLENS_ENVIRONMENT=production` + 默认 SECRET_KEY | 拒绝启动（RuntimeError） |
| 生产模式 SPA | `GET /` 200，index.html 正常 |
| `/api/health` | `status=ok, environment=production` |
| 无效模型 Key | `POST /settings/model-key` → 400，未保存 |
| 设置响应 | 不含 `sk-`，`has_api_key=false` |

## 7. 未被自动化覆盖的部分

| 项 | 原因 | 建议 |
| --- | --- | --- |
| DeepSeek 生成式回答/翻译 | 无 API Key | 配置后做人工回归（测试用例已设计） |
| PostgreSQL | 本地无实例 | 在部署环境执行迁移与回归 |
| 扫描版 PDF OCR | 功能未实现 | 接入 OCR 后补充语料测试 |
| 超大 PDF（200+ 页） | 时间/资源 | 增加性能基准与超时测试 |
| 并发上传 | 单进程测试 | 压测 + 队列化 |
| 跨浏览器 | 仅 Chrome | 增加 Firefox/WebKit 项目 |
| 证据“结论是否被支持” | 当前只核验引用是否在原文中 | P8 增加 claim-level 检查 |
| 运行中暂停/继续 | 浏览器时序难以稳定复现 | 已用 live SSE 测试：paused 前 0 delta；建议人工复测 |
| SSE 断开后的任务恢复 | 无后台队列 | 后续阶段增加持久化执行器 |
| 生成式冲突/演化 | 无 API Key | 配置后做人工回归 |
| 多论文主题聚类 | 未实现 | 需要语义聚类，当前只有词频 |
| 研究情报外部数据 | 未接入 | 当前只分析资料库，UI 明确标注 |
| 知识自动标签 | 规则/关键词 | 中文词表有限，非语义模型 |
| 知识聚类 | 标签聚类 | 不是主题模型 |
| 知识合并且来源版本 | 合并删除来源 | 目标条目保留合并版本 |
| 学术成果 | 抽取式模板，不是完整综述 | 需研究者改写 |
| 成果质检 | 词法/结构启发式 | 无 claim-level 语义验证 |
| 队列 | 单进程单 worker | 多实例需 Redis/Celery |
| 增量索引 | 按论文文档缓存 | BM25 全局仍重建 |
| 限流 | 进程内滑动窗口 | 多进程不共享 |
| Postgres | 本机无实例 | 未实机验证 |
| PPT 产物 | 只有大纲，无 .pptx | 后续阶段 |
| hypothesis/external 自动生成 | 需 RI/外部数据源 | P5/P8 接入 |

## 8. 复现截图

```bash
cd qa
node run.mjs
# 输出 qa/screenshots/*.png
```

依赖系统 Chrome：`chromium.launch({ channel: "chrome" })`；无需额外下载浏览器。

## V4 unified research context

```text
cd backend
python -m pytest tests/test_v4_context.py -q -p no:cacheprovider
python -m pytest tests -q -p no:cacheprovider

cd ../frontend
npm run build

cd ../qa
node run.mjs
```

V4 tests cover knowledge RAG, project context, real image metadata with explicit vision limitation, artifact generation/check confirmation, and cross-user resource isolation.

## V4.1 real-agent hardening

~~~text
cd backend
python -m pytest tests/test_v41_agent_loop.py -q -p no:cacheprovider
python -m pytest tests/test_v41_vision_security.py -q -p no:cacheprovider
python -m pytest tests -q -p no:cacheprovider
~~~

The V4.1 tests use a mock LLM provider and a mock VisionProvider only. They prove the loop, registry, budgets, signed confirmation and image-bytes handoff; they do not prove real model or real vision quality.

Real-model and real-vision smoke scripts are intentionally skipped unless explicit authorization env vars are set:

~~~text
PAPERLENS_REAL_LLM_AUTHORIZED=1 python backend/scripts/v41_real_llm_smoke.py
PAPERLENS_REAL_VISION_AUTHORIZED=1 python backend/scripts/v41_vision_smoke.py
~~~
