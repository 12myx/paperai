# PaperLens AI · Project Status

> 日期：2026-11-06  
> 代码基线：HEAD `d8e415e` + 未提交的 U1/U2 与 V4 改动  
> 本地验证环境：Windows / Python 3.12 / SQLite / 无生成式模型密钥

## 1. 当前状态

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 论文上传、解析、阅读 | 已完成 | 114 backend tests；38-step browser E2E |
| 论文 RAG / 对话 / 引用 | 已完成 | 本地抽取模式与 QA |
| 个人知识库 Chat 检索 | 已完成 | `search_knowledge` / `read_knowledge`；V4 tests |
| 项目级 Chat 上下文 | 已完成 | `get_project_context`；项目目标/描述/笔记/资源 |
| 图像真实文件读取 | 已完成 | `read_image` 读取真实 PNG/JPEG 元数据与哈希 |
| 图像语义视觉分析 | 受外部依赖限制 | 当前模型客户端无视觉输入；明确返回能力限制 |
| 论文知识包（选择论文→生成→存入知识库） | 已完成 | 预检、知识包、`save-to-knowledge`；3 tests |
| 学术成果 Chat 查询/生成/检查/导出 | 已完成 | `list/read/generate/check/export_artifact`；V4 tests |
| 项目关联成果 | 已完成 | 生成时将 artifact 写入 ProjectItem |
| 资源级引用 | 已完成 | knowledge/image/artifact/project 引用可跳转 |
| 用户显式选择知识/图片/成果 | 部分完成 | 后端支持 `knowledge_ids/image_ids/artifact_ids`；知识/图片/成果页面提供单资源“在 Chat 中使用”入口；尚无合并多选器 |
| 真实生成式模型工具调用 | 未验证 | 当前环境无 API Key；本地确定性链路已验证 |
| PostgreSQL / Docker 实机 | 未验证 | 本轮只验证本地 SQLite |
| 数据库 schema 变更 | 无 | 复用既有 Evidence/AcademicArtifact/ProjectItem |

## 1.1 V4.1 additions

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 真实 LLM 工具循环代码 | 已实现、Mock 验证 | 5 个 mock-provider 测试 |
| 真实模型闭环 | 未验证 | 无 API Key；提供真实模型 smoke 脚本 |
| 工具轮数/调用/时间/Token 预算 | 已实现 | 配置与 loop 代码 |
| 写操作签名确认 | 已实现并测试 | HMAC + 用户/参数/过期/重放 |
| Prompt Injection（本地恶意知识） | 已测试 | 不触发写操作或越权 |
| Vision Provider 接口 | 已实现 | mock 真实图片字节测试 |
| 真实视觉语义 | 未实现 | 无视觉 Provider |
| 多资源选择器 | 已实现并浏览器验证 | 72 个可选资料行；显式 ID 请求 |
| 回归 | 114 backend / 38 browser / 88 API（历史全流程）/ 17 final smoke | 最终运行 |

## 1.2 V4.2 additions

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| Action 持久化 | 已验证 | action_requests + 状态 API |
| Action 并发领取 | 已验证（SQLite 线程） | 20 并发仅 1 成功 |
| Action 重启恢复 | 已验证 | 重启后 pending 可确认，重放 400 |
| 真实 DeepSeek 工具循环 | 已验证 | provider=deepseek；4 次工具；8 引用 |
| 自动检索开关 | 已验证 | 后端 3 测试 + 浏览器请求体 |
| 资源排除 | 已验证 | 工具/解析器/UI |
| 多资源选择器 | 已验证 | 72 行，知识/图片/成果 |
| 图表 P0 重分类 | 已验证 | 62 页面截图移入快照层，0 误入精选 |
| 资源使用透明度 | 部分 | resource_usage 表 + 运行资源 API + UI 面板；retrieved 覆盖仍不完整 |
| Docker/PostgreSQL | 跳过 | 本机未安装 Docker/psql |

## 2. 仍存在的限制

- 没有真实视觉模型，不能声称“看过图片像素”；只能读取真实图片文件并提供图注/元数据，并明确提示视觉能力限制。
- 没有真实 LLM Key，模型工具循环未在真实模型上验证；本地 Agent 工具链已通过真实数据测试。
- 前端尚未提供完整的“多资源勾选器”；当前支持项目范围、自动检索，以及从引用跳转到具体资源。
- Prompt Injection 只在工具边界和输入来源上做了防御性设计，未做真实模型注入基准。
- 未验证大规模论文库、多用户并发和 PostgreSQL 迁移。

## 3. 下一步优先级

1. 配置真实视觉 Provider（必须明确费用与授权）后，补充图像像素级验收。
2. 配置真实 LLM Key 后，验证模型自主选择 27 个工具的工具循环。
3. 增加前端显式资源选择器（知识/图片/成果），并复用 `knowledge_ids/image_ids/artifact_ids`。
4. 在 PostgreSQL 上跑完整迁移与并发回归。