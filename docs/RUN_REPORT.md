# PaperLens AI · V4 Run Report

> 运行时间：2026-11-06  
> 位置：本地 Windows，SQLite，`http://127.0.0.1:8000`  
> 模型：回归默认本地抽取；真实 DeepSeek smoke 使用临时 Key 后已清除。

## 1. 环境

- Python 3.12
- FastAPI + SQLAlchemy + SQLite WAL
- React 18 + Vite 6
- Playwright + system Chrome
- QA 账号：`qa@paperlens.ai`

## 2. 命令与结果

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q -p no:cacheprovider` | **114 passed** |
| `node run.mjs` (qa) | **38 / 38 passed**，0 console/page error |
| `python %TEMP%\paperlens_flow_test.py` | **88 / 88 passed（历史全流程）** |
| `python scripts/v42_api_smoke.py` | **17 / 17 passed（最终 API smoke）** |
| `npm run build` (frontend) | 通过 |
| V4 专项 `tests/test_v4_context.py` | **6 passed** |
| V4.1 mock loop `tests/test_v41_agent_loop.py` | **5 passed** |
| V4.1 vision/security `tests/test_v41_vision_security.py` | **3 passed** |
| V4.2 persistent action `tests/test_v42_actions.py` | **2 passed** |
| V4.2 resource control `tests/test_v42_resource_control.py` | **3 passed** |
| V4.2 resource usage `tests/test_v42_usage.py` | **1 passed** |
| V4.2 figure P0 `tests/test_v42_figures.py` | **4 passed** |
| V4.2 knowledge pack `tests/test_v42_knowledge_pack.py` | **4 passed** |
| V4.2 research async `tests/test_v42_research_intel.py` | **1 passed** |
| V4.2 UX `tests/test_v42_ux.py` | **3 passed** |
| V4.2 compare dimensions `tests/test_v42_research_dimensions.py` | **2 passed** |

## 3. 真实浏览器验收

- 知识库问题：Chat 先执行 `search_knowledge`，来源卡显示“知识”，点击进入 `/app/knowledge?focus=<id>` 并打开条目。
- 图像问题：Chat 执行 `search_images` → `read_image` → `analyze_image`；真实读取 640×360、5637 bytes 图片元数据；明确显示“无法完成真正的视觉分析”。
- 成果检查：Chat 执行 `list_artifacts` → `check_artifact`，返回问题位置/严重程度/建议；来源卡可跳转成果。
- 成果生成：Chat 先给出待确认 action；点击“确认并执行”后写入 AcademicArtifact，并可在 Artifacts 页面查看。
- 项目级 Chat：API 验收读取项目目标、描述、笔记、关联论文/知识，并生成 project 引用。
- 显式上下文：访问 `/app?knowledge=<id>` 显示“本次指定上下文”，stream request 携带 `knowledge_ids`，回答使用该资源。

## 4. 测试数据

测试使用本地 QA 数据库与新建隔离账号；未清空或覆盖真实用户数据。测试产生的 artifacts、knowledge、projects 仅存在本地开发数据库。

## 4.1 V4.1 additions

- Mock LLM tool loop: search tool, unknown tool, pending write, tamper/replay, tool budget.
- Signed write action: user-bound, args-bound, expires, single use.
- Vision Provider interface + mock image bytes; no real vision provider.
- Multi-resource picker browser test; explicit IDs sent in chat request.
- Prompt injection from malicious knowledge did not trigger tools.

## 4.2 V4.2 additions

- Persistent action_requests table and atomic claim.
- 20-way concurrent confirm: 1 success, 19 conflicts, one write.
- Server restart action persistence verified.
- auto_retrieval and exclude_ids enforced by resolver/tools; browser request body verified.
- Real DeepSeek smoke passed; temporary key removed afterward.
- Local 6-chat stress: 6/6, avg 3421ms, p95 3805ms.
- Docker/PostgreSQL skipped because binaries are absent.

## 5. 未执行

- 真实 LLM 工具调用（无 Key，未产生费用）。
- 真实视觉模型（无视觉 Provider）。
- Docker/Railway/PostgreSQL 实机。
- 10+ 大资料库压力、跨浏览器矩阵、人工注入基准。

## 6. 结论

V4 的核心跨模块链路在当前本地环境可运行，并通过真实数据库与浏览器验证；视觉语义和真实模型推理明确标记为受外部依赖限制。