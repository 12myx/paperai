"""The PaperLens agent tool belt.

Each tool performs a real database or filesystem operation. Tools that write
user data (knowledge items, annotations, exports) are *guarded*: unless the
caller explicitly allows writes they return a pending action for the user to
confirm in the UI.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from ..models import (
    AcademicArtifact,
    Annotation,
    ArtifactQualityReport,
    Chunk,
    Conversation,
    ExportRecord,
    Figure,
    KnowledgeItem,
    Message,
    Paper,
    Project,
    ProjectItem,
    User,
    utcnow,
)
from . import analysis
from .export import build_export
from .llm import LLMClient, LLMError, ModelConfig, system_prompt
from .rag import search as rag_search
from .actions import create_action
from .storage import safe_filename, storage
from .vision import get_vision_provider
from . import research_context

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "在用户资料库中搜索论文（按标题、作者、摘要、标签）。返回论文 id、标题、年份与状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_paper",
            "description": "读取指定论文的元数据、章节大纲与指定章节的原文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "section": {"type": "string", "description": "章节标题（可省略）"},
                },
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_chunks",
            "description": "检索与问题最相关的论文原文片段，返回带页码和章节的引用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                    "top_k": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_paper",
            "description": "按指定模式总结论文（一句话、摘要、章节、方法、实验、创新点、局限、未来方向等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "mode": {"type": "string", "enum": list(analysis.SUMMARY_MODES.keys())},
                },
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "translate_content",
            "description": "翻译论文内容，保留术语与公式。需要已配置生成式模型。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_language": {"type": "string", "default": "简体中文"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_papers",
            "description": "对多篇论文进行结构化对比（共同点、差异、方法、实验、结论）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                    "focus": {"type": "string"},
                },
                "required": ["paper_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_intelligence",
            "description": "基于资料库生成研究情报：全景、证据矩阵、观点冲突或方法演化。只分析当前范围，不接入外部文献。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要分析的研究问题"},
                    "section": {"type": "string", "enum": ["landscape", "matrix", "conflicts", "evolution"], "default": "landscape"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_knowledge",
            "description": "根据用户指令从论文中提取结构化知识（创新点、方法、结论、可引用片段）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_knowledge",
            "description": "把一条研究知识保存到个人知识库。这是写操作，需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "kind": {"type": "string", "enum": ["note", "summary", "insight", "method", "result", "question", "quote"]},
                    "paper_id": {"type": "string"},
                    "page": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "project_id": {"type": "string"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_annotation",
            "description": "在论文指定页保存一条批注/高亮。这是写操作，需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "quote": {"type": "string"},
                    "page": {"type": "integer"},
                    "color": {"type": "string", "enum": ["yellow", "blue", "green", "red", "purple"]},
                    "note": {"type": "string"},
                },
                "required": ["paper_id", "quote", "page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_figures",
            "description": "列出论文中已提取的图表，可按描述检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_research_gap",
            "description": "基于论文证据分析研究缺口、分歧与可验证假设，并给出证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "生成研究报告（Markdown），主题可自定义，必须基于资料库论文证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_document",
            "description": "将内容导出为真实文件（pdf/docx/md/txt/csv/json）。这是写操作，需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Markdown 内容"},
                    "format": {"type": "string", "enum": ["pdf", "docx", "md", "txt", "csv", "json"]},
                    "kind": {"type": "string"},
                },
                "required": ["title", "content", "format"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "搜索用户个人知识库，返回知识标题、内容片段、标签、来源论文和所属项目。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "研究问题或关键词"},
                    "limit": {"type": "integer", "default": 6},
                    "project_id": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_knowledge",
            "description": "读取用户个人知识库中的完整知识条目。",
            "parameters": {
                "type": "object",
                "properties": {"knowledge_id": {"type": "string"}},
                "required": ["knowledge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_context",
            "description": "读取当前研究项目的目标、描述、进度、笔记与已关联资源。",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_resources",
            "description": "在指定研究项目内检索论文、知识、图片、成果和笔记，严格限制在项目范围内。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "resource_type": {"type": "string", "enum": ["paper", "knowledge", "image", "artifact", "note", "all"], "default": "all"},
                    "query": {"type": "string", "default": ""},
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_images",
            "description": "检索用户图像库中的真实图表/图片，返回图片 id、论文、页码和图注。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "paper_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 6},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_image",
            "description": "读取真实图片文件，返回尺寸、哈希、文件大小和来源；不进行视觉推断。",
            "parameters": {
                "type": "object",
                "properties": {"image_id": {"type": "string"}},
                "required": ["image_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": "请求对图片进行视觉分析。只有配置了真实视觉模型时才可用；未配置时必须明确返回能力限制。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_id": {"type": "string"},
                    "question": {"type": "string", "default": "解释这张图"},
                },
                "required": ["image_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_artifacts",
            "description": "列出用户已有学术成果（综述、开题报告、研究计划等），可按项目和类型筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "default": ""},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact",
            "description": "读取一份已有学术成果的正文、质量状态和引用。",
            "parameters": {
                "type": "object",
                "properties": {"artifact_id": {"type": "string"}},
                "required": ["artifact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_artifact",
            "description": "基于论文证据生成一份学术成果并保存到成果库。这是写操作，需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["literature_review", "reading_report", "comparison_report", "direction_analysis", "proposal_draft", "research_plan", "experiment_design", "ppt_outline"]},
                    "title": {"type": "string"},
                    "scope_type": {"type": "string", "default": "papers"},
                    "scope_id": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                    "knowledge_ids": {"type": "array", "items": {"type": "string"}},
                    "image_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_artifact",
            "description": "检查学术成果的结构、证据、引用、逻辑和格式问题，返回问题位置与修改建议。",
            "parameters": {
                "type": "object",
                "properties": {"artifact_id": {"type": "string"}},
                "required": ["artifact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_artifact",
            "description": "将已有学术成果导出为 md/pdf/docx 文件。这是写操作，需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "format": {"type": "string", "enum": ["md", "pdf", "docx"], "default": "md"},
                },
                "required": ["artifact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_research_history",
            "description": "检索用户过往的研究对话与结论。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
]



WRITE_TOOLS = {"save_knowledge", "save_annotation", "export_document", "generate_artifact", "export_artifact"}
TOOL_NAMES = {
    "search_papers", "read_paper", "retrieve_chunks", "summarize_paper", "translate_content",
    "compare_papers", "research_intelligence", "extract_knowledge", "save_knowledge",
    "save_annotation", "extract_figures", "analyze_research_gap", "generate_report",
    "export_document", "search_research_history", "search_knowledge", "read_knowledge",
    "get_project_context", "search_project_resources", "search_images", "read_image",
    "analyze_image", "list_artifacts", "read_artifact", "generate_artifact",
    "check_artifact", "export_artifact",
}

class ToolError(RuntimeError):
    pass


class ToolRunner:
    def __init__(
        self,
        db: Session,
        user: User,
        config: ModelConfig | None,
        scope_ids: list[str] | None = None,
        allow_writes: bool = False,
        exclude_ids: list[str] | None = None,
        auto_retrieval: bool = True,
    ) -> None:
        self.db = db
        self.user = user
        self.config = config
        self.scope_ids = scope_ids
        self.allow_writes = allow_writes
        self.exclude_ids = set(exclude_ids or [])
        self.auto_retrieval = auto_retrieval
        self.vision_provider = get_vision_provider(config)
        self.counter = 0
        self.citations: list[dict] = []

    # ------------------------------------------------------------------ utils
    def _register(self, result: dict) -> dict:
        citations = result.get("citations") or []
        mapping: dict[str, str] = {}
        existing = {c["chunk_id"]: c["key"] for c in self.citations}
        for citation in citations:
            old = citation.get("key", "")
            chunk_id = citation.get("chunk_id")
            if chunk_id in existing:
                mapping[old] = existing[chunk_id]
                continue
            self.counter += 1
            new = f"C{self.counter}"
            mapping[old] = new
            citation["key"] = new
            existing[chunk_id] = new
            self.citations.append(citation)
        result["citations"] = [c for c in citations if c.get("key") in set(mapping.values())]
        summary = result.get("summary", "")
        result["summary"] = re.sub(r"\[C(\d+)\]", lambda m: f"[{mapping.get('C' + m.group(1), m.group(0))}]", summary)
        return result

    def _scoped_ids(self, requested: list[str] | None) -> list[str] | None:
        if requested is None:
            return None if self.scope_ids is None else [item for item in self.scope_ids if item not in self.exclude_ids]
        if self.scope_ids is None:
            return [item for item in dict.fromkeys(requested) if item not in self.exclude_ids]
        allowed = set(self.scope_ids)
        return [item for item in dict.fromkeys(requested) if item in allowed and item not in self.exclude_ids]

    def _papers(self, paper_ids: list[str] | None) -> list[Paper]:
        ids = self._scoped_ids(paper_ids)
        query = select(Paper).where(Paper.user_id == self.user.id)
        if ids is not None:
            query = query.where(Paper.id.in_(ids))
        return list(self.db.execute(query.order_by(Paper.created_at)).scalars().all())

    def _paper(self, paper_id: str) -> Paper:
        if paper_id in self.exclude_ids:
            raise ToolError("该论文已被用户排除，不能读取")
        paper = self.db.get(Paper, paper_id)
        if paper is None or paper.user_id != self.user.id:
            raise ToolError("未找到该论文，或无权访问")
        if self.scope_ids is not None and paper.id not in set(self.scope_ids):
            raise ToolError("该论文不在本次研究范围内")
        return paper

    def _guard(self, name: str, args: dict, label: str, preview: str) -> dict:
        if self.allow_writes:
            return {}
        token = create_action(self.db, self.user, name, args)
        return {
            "pending": True,
            "action": {"tool": name, "args": args, "label": label, "preview": preview[:1200], **token},
            "summary": f"已生成待确认操作：{label}。请用户在界面中确认后执行。",
            "citations": [],
            "data": {},
        }

    # ------------------------------------------------------------------ tools
    async def run(self, name: str, args: dict) -> dict:
        if name not in TOOL_NAMES:
            raise ToolError(f"未知工具：{name}")
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ToolError(f"未知工具：{name}")
        try:
            result = await handler(**args)
        except TypeError as exc:
            raise ToolError(f"工具参数错误：{exc}") from exc
        return self._register(result)

    async def tool_search_papers(self, query: str, limit: int = 8) -> dict:
        if not self.auto_retrieval:
            raise ToolError("自动检索已关闭，请由用户显式选择资料")
        pattern = f"%{query.strip()}%"
        query_stmt = select(Paper).where(
            Paper.user_id == self.user.id,
            or_(
                Paper.title.ilike(pattern),
                Paper.abstract.ilike(pattern),
                Paper.authors.ilike(pattern),
                cast(Paper.tags, String).ilike(pattern),
            ),
        )
        if self.scope_ids is not None:
            query_stmt = query_stmt.where(Paper.id.in_(self.scope_ids))
        rows = self.db.execute(query_stmt.limit(max(1, min(limit, 20)))).scalars().all()
        if not rows and query:
            for cite in rag_search(self.db, self.user.id, query, self.scope_ids, top_k=limit):
                paper = self.db.get(Paper, cite["paper_id"])
                if paper and paper not in rows:
                    rows.append(paper)
        lines = [f"在资料库中匹配到 {len(rows)} 篇论文：" if rows else "资料库中没有匹配的论文。"]
        for paper in rows:
            lines.append(f"- {paper.title} ({paper.year or 'n.d.'}) · id={paper.id} · 状态={paper.status}")
        return {"summary": "\n".join(lines), "citations": [], "data": {"papers": [{"id": p.id, "title": p.title, "year": p.year} for p in rows]}}

    async def tool_read_paper(self, paper_id: str, section: str | None = None) -> dict:
        paper = self._paper(paper_id)
        sections = self.db.execute(
            select(Chunk.section_title).where(Chunk.paper_id == paper.id).distinct()
        ).scalars().all()
        chunks = self.db.execute(
            select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)
        ).scalars().all()
        selected = chunks
        if section:
            selected = [c for c in chunks if section.lower() in c.section_title.lower()] or chunks
        citations = []
        blocks = []
        budget = 0
        for chunk in selected:
            if budget > 9000:
                break
            citations.append(
                {
                    "key": f"C{len(citations) + 1}",
                    "chunk_id": chunk.id,
                    "paper_id": paper.id,
                    "paper_title": paper.title,
                    "paper_year": paper.year,
                    "section": chunk.section_title,
                    "page": chunk.page_start,
                    "page_end": chunk.page_end,
                    "quote": chunk.text[:1400],
                    "score": 1.0,
                    "kind": chunk.kind,
                    "tags": list(chunk.tags or []),
                }
            )
            blocks.append(f"[C{len(citations)}] 第 {chunk.page_start} 页 · {chunk.section_title}\n{chunk.text[:1600]}")
            budget += len(chunk.text)
        header = (
            f"# {paper.title}\n作者：{paper.authors or '未知'} · 年份：{paper.year or '未知'} · 页数：{paper.page_count}\n"
            f"摘要：{(paper.abstract or '（未提取到摘要）')[:900]}\n章节：{' / '.join(sections)}\n\n"
        )
        return {"summary": header + "\n\n".join(blocks), "citations": citations, "data": {"paper_id": paper.id, "sections": list(sections)}}

    async def tool_retrieve_chunks(self, query: str, paper_ids: list[str] | None = None, top_k: int = 8) -> dict:
        if not self.auto_retrieval:
            raise ToolError("自动检索已关闭，请由用户显式选择资料")
        ids = self._scoped_ids(paper_ids)
        if ids is not None and not ids:
            return {"summary": "所选研究范围内没有可检索的论文。", "citations": [], "data": {"count": 0}}
        citations = rag_search(self.db, self.user.id, query, ids, top_k=max(1, min(top_k, 12)))
        if not citations:
            return {"summary": "在所选范围内没有检索到与问题相关的原文片段。", "citations": [], "data": {"count": 0}}
        lines = [f"检索到 {len(citations)} 个相关片段："]
        for citation in citations:
            lines.append(f"[{citation['key']}] 《{citation['paper_title']}》 第 {citation['page']} 页 · {citation['section']}\n{citation['quote'][:700]}")
        return {"summary": "\n\n".join(lines), "citations": citations, "data": {"count": len(citations)}}

    async def tool_summarize_paper(self, paper_id: str, mode: str = "abstract") -> dict:
        paper = self._paper(paper_id)
        if mode not in analysis.SUMMARY_MODES:
            mode = "abstract"
        text, citations, local = await analysis.generative_summary(self.db, self.user, self.config, paper, mode)
        return {
            "summary": text,
            "citations": citations,
            "data": {"paper_id": paper.id, "mode": mode, "local": local},
        }

    async def tool_translate_content(self, text: str, target_language: str = "简体中文") -> dict:
        if self.config is None:
            raise ToolError("翻译需要生成式模型：请在「设置 → AI 模型」配置 DeepSeek API Key。")
        translated = await analysis.translate_text(self.config, text[:8000], target_language)
        return {"summary": translated, "citations": [], "data": {"target_language": target_language, "local": False}}

    async def tool_compare_papers(self, paper_ids: list[str], focus: str = "") -> dict:
        papers = [self._paper(pid) for pid in paper_ids]
        if len(papers) < 2:
            raise ToolError("对比至少需要两篇论文")
        text, citations, local = await analysis.generative_compare(self.db, self.config, papers, focus)
        return {"summary": text, "citations": citations, "data": {"paper_ids": [p.id for p in papers], "local": local}}

    async def tool_research_intelligence(self, question: str, section: str = "landscape") -> dict:
        papers = self._papers(None)
        if not papers:
            raise ToolError("资料库中没有可分析的论文")
        papers = papers[:8]
        paper_ids = [paper.id for paper in papers]
        section = section if section in {"landscape", "matrix", "conflicts", "evolution"} else "landscape"
        if section == "matrix":
            from .multipaper import build_matrix
            result = await build_matrix(self.db, self.user, papers, self.config, force=False)
            rows = result.get("rows") or []
            lines = ["## 证据矩阵（资料库范围）", "", result.get("note") or ""]
            for row in rows:
                fields = row.get("fields") or {}
                lines.append(f"### {row.get('title')}（{row.get('year') or 'n.d.'}）")
                for field, label in (("research_question", "问题"), ("method", "方法"), ("dataset", "数据"), ("metrics", "指标"), ("findings", "发现"), ("limitations", "局限")):
                    cell = fields.get(field) or {}
                    if cell.get("text") and cell.get("text") != "未提及":
                        lines.append(f"- **{label}**：{cell.get('text')}（p.{cell.get('page') or '?'}）")
                lines.append("")
            return {"summary": "\n".join(lines), "citations": result.get("citations") or [], "data": result}

        if section in {"conflicts", "evolution"}:
            from .multipaper import build_conflicts, build_evolution
            result = await (build_conflicts(self.db, self.user, papers, self.config, force=False) if section == "conflicts" else build_evolution(self.db, self.user, papers, self.config, force=False))
            lines = [f"## {'观点冲突' if section == 'conflicts' else '方法演化'}（资料库范围）", "", result.get("note") or ""]
            if section == "conflicts":
                for item in result.get("conflicts") or []:
                    lines.append(f"- {item.get('question')}：{item.get('stance_a')} vs {item.get('stance_b')}")
                if not result.get("conflicts"):
                    lines.append("没有找到同时满足问题相同、条件可比且有证据的冲突；这不等于没有冲突。")
            else:
                for item in result.get("timeline") or []:
                    lines.append(f"- {item.get('year') or '年份未知'} · {item.get('title')}：{item.get('method')}")
                if not result.get("relations"):
                    lines.append("没有生成有证据支持的方法继承关系；时间线只按真实年份排列。")
            return {"summary": "\n".join(lines), "citations": result.get("citations") or [], "data": result}

        from .intelligence import build_overview
        result = await build_overview(
            self.db, self.user, scope_type="papers", scope_id=None,
            paper_ids=paper_ids, config=self.config, force=False,
        )
        landscape = result["reports"]["landscape"]
        data = landscape["data"]
        lines = ["## 资料库研究全景", "", data.get("overview") or "", "", data.get("note") or ""]
        for key, label in (("core_questions", "核心问题"), ("technical_routes", "技术路线"), ("challenges", "挑战"), ("future_directions", "未来方向")):
            lines.append(f"### {label}")
            for item in (data.get(key) or [])[:5]:
                key_mark = f" [{item.get('evidence_key')}]" if item.get("evidence_key") else ""
                lines.append(f"- {item.get('text')}{key_mark}（p.{item.get('page') or '?'}）")
            lines.append("")
        return {"summary": "\n".join(lines), "citations": landscape.get("citations") or [], "data": data}

    async def tool_extract_knowledge(self, instruction: str, paper_ids: list[str] | None = None) -> dict:
        ids = self._scoped_ids(paper_ids)
        if ids is not None and not ids:
            return {"summary": "所选研究范围内没有可提取的论文。", "citations": [], "data": {}}
        citations = rag_search(self.db, self.user.id, instruction, ids, top_k=8)
        if not citations:
            return {"summary": "没有找到与提取指令相关的原文。", "citations": [], "data": {}}
        evidence = "\n\n".join(f"[{c['key']}] {c['quote'][:800]}" for c in citations)
        if self.config is None:
            lines = ["## 本地抽取结果", ""]
            for citation in citations[:5]:
                lines.append(f"- **{citation['paper_title']}**（第 {citation['page']} 页 · {citation['section']}）：{citation['quote'][:260]} [{citation['key']}]")
            lines.append("\n> 本地模式只做片段级抽取，未做跨片段综合。")
            return {"summary": "\n".join(lines), "citations": citations, "data": {"local": True}}
        messages = [
            {"role": "system", "content": system_prompt("deep_read")},
            {"role": "user", "content": f"提取指令：{instruction}\n\n仅基于以下证据提取，输出结构化 Markdown，每条附 [C#]：\n\n{evidence}"},
        ]
        response = await LLMClient(self.config).complete(messages, temperature=0.2)
        return {"summary": response["content"], "citations": citations, "data": {"local": False}}

    async def tool_save_knowledge(
        self, title: str, content: str, kind: str = "note",
        paper_id: str | None = None, page: int | None = None, tags: list[str] | None = None,
        project_id: str | None = None, force: bool = False,
    ) -> dict:
        from .knowledge import DUPLICATE_THRESHOLD, find_duplicate
        candidate, score = find_duplicate(self.db, self.user, title, content)
        if candidate is not None and score >= DUPLICATE_THRESHOLD and not force:
            args = {"title": title, "content": content, "kind": kind, "paper_id": paper_id, "page": page, "tags": tags or [], "project_id": project_id, "force": True}
            guard = self._guard(
                "save_knowledge",
                args,
                "保存相似知识（需确认）",
                f"与「{candidate.title}」相似度 {score:.0%}。确认后会仍然创建新条目。\n\n{content}",
            )
            if guard:
                return guard
        guard = self._guard("save_knowledge", {"title": title, "content": content, "kind": kind, "paper_id": paper_id, "page": page, "tags": tags or [], "project_id": project_id}, "保存到知识库", content)
        if guard:
            return guard
        if paper_id:
            self._paper(paper_id)
        if project_id:
            self._project(project_id)
        item = KnowledgeItem(
            user_id=self.user.id, title=title[:390], content=content, kind=kind,
            source_paper_id=paper_id, source_page=page, tags=tags or [], project_id=project_id,
        )
        self.db.add(item)
        self.db.flush()
        from .knowledge import ensure_meta
        ensure_meta(self.db, item)
        self.db.commit()
        return {"summary": f"已保存到知识库：{title}", "citations": [], "data": {"knowledge_id": item.id}}

    async def tool_save_annotation(
        self, paper_id: str, quote: str, page: int, color: str = "yellow", note: str | None = None,
    ) -> dict:
        guard = self._guard(
            "save_annotation",
            {"paper_id": paper_id, "quote": quote, "page": page, "color": color, "note": note},
            "保存论文批注", quote,
        )
        if guard:
            return guard
        paper = self._paper(paper_id)
        annotation = Annotation(
            user_id=self.user.id, paper_id=paper.id, page_number=page,
            color=color, quote=quote[:4000], note=note, rects=[],
        )
        self.db.add(annotation)
        self.db.commit()
        return {"summary": f"已在《{paper.title}》第 {page} 页保存批注", "citations": [], "data": {"annotation_id": annotation.id}}

    async def tool_extract_figures(self, paper_id: str | None = None, query: str = "") -> dict:
        statement = select(Figure).where(
            Figure.user_id == self.user.id,
            Figure.ignored.is_(False),
            Figure.is_page_snapshot.is_(False),
        )
        if paper_id:
            paper = self._paper(paper_id)
            statement = statement.where(Figure.paper_id == paper.id)
        elif self.scope_ids is not None:
            statement = statement.where(Figure.paper_id.in_(self.scope_ids))
        figures = list(self.db.execute(statement.limit(200)).scalars().all())
        if query:
            figures = [f for f in figures if query.lower() in ((f.caption or "") + (f.note or "")).lower()] or figures
        data = [
            {
                "id": f.id, "paper_id": f.paper_id, "page": f.page_number, "kind": f.kind,
                "caption": (f.caption or "")[:400], "image_url": f"/api/figures/{f.id}/image",
                "table_markdown": (f.table_markdown or "")[:2000],
            }
            for f in figures[:20]
        ]
        lines = [f"找到 {len(data)} 个图表：" if data else "没有找到图表。"]
        for item in data[:12]:
            lines.append(f"- p.{item['page']} · {item['kind']} · {item['caption'][:160]}")
        return {"summary": "\n".join(lines), "citations": [], "data": {"figures": data}}

    async def tool_analyze_research_gap(self, paper_ids: list[str] | None = None) -> dict:
        papers = self._papers(paper_ids)
        if not papers:
            raise ToolError("资料库中没有可分析的论文")
        if len(papers) > 8:
            papers = papers[:8]
        text, citations, local = await analysis.generative_gap_analysis(self.db, self.config, papers)
        return {"summary": text, "citations": citations, "data": {"paper_ids": [p.id for p in papers], "local": local}}

    async def tool_generate_report(self, topic: str, paper_ids: list[str] | None = None) -> dict:
        papers = self._papers(paper_ids)
        if not papers:
            raise ToolError("资料库中没有可用的论文")
        if self.config is None:
            blocks = [analysis.LOCAL_BANNER, f"# 研究报告：{topic}\n"]
            all_citations: list[dict] = []
            for paper in papers[:6]:
                text, citations = await self._summary_and_citations(paper)
                blocks.append(f"## {paper.title}\n{text}\n")
                all_citations.extend(citations)
            return {"summary": "\n".join(blocks), "citations": all_citations, "data": {"local": True, "topic": topic, "paper_ids": [p.id for p in papers]}}
        blocks, citations = [], []
        for paper in papers[:8]:
            context, cites = analysis.paper_context(self.db, paper, max_chars=5000)
            blocks.append(f"### {paper.title}\n{context}")
            for cite in cites:
                cite["key"] = f"C{len(citations) + 1}"
                citations.append(cite)
        messages = [
            {"role": "system", "content": system_prompt("multi_paper")},
            {"role": "user", "content": f"撰写一份关于「{topic}」的研究报告（Markdown），结构：研究背景 / 文献概况 / 方法与结果对比 / 共识与分歧 / 研究缺口 / 建议的下一步实验 / 参考资料。所有判断必须基于以下论文证据并带 [C#] 引用。\n\n" + "\n\n".join(blocks)},
        ]
        response = await LLMClient(self.config).complete(messages, temperature=0.3, max_tokens=3200)
        return {"summary": response["content"], "citations": citations, "data": {"local": False, "topic": topic, "paper_ids": [p.id for p in papers]}}

    async def _summary_and_citations(self, paper: Paper) -> tuple[str, list[dict]]:
        text, citations = analysis.extractive_summary(self.db, paper, "abstract")
        return text, citations

    async def tool_export_document(self, title: str, content: str, format: str = "md", kind: str = "report") -> dict:
        guard = self._guard("export_document", {"title": title, "content": content, "format": format, "kind": kind}, f"导出 {format.upper()} 文件", content)
        if guard:
            return guard
        data, ext = build_export(format, title, content)
        filename = f"{safe_filename(title, 'paperlens-report')}-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"
        relative = storage.save_export(self.user.id, filename, data)
        record = ExportRecord(
            user_id=self.user.id, kind=kind, title=title[:290], format=ext,
            filename=filename, path=relative, size_bytes=len(data),
            meta={"tool": "export_document"},
        )
        self.db.add(record)
        self.db.commit()
        return {
            "summary": f"已导出 {ext.upper()} 文件：{filename}",
            "citations": [],
            "data": {"export_id": record.id, "filename": filename, "download_url": f"/api/exports/{record.id}/download", "size_bytes": len(data)},
        }

    async def tool_search_research_history(self, query: str, limit: int = 5) -> dict:
        pattern = f"%{query.strip()}%"
        rows = self.db.execute(
            select(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == self.user.id, Message.content.ilike(pattern))
            .order_by(Message.created_at.desc())
            .limit(max(1, min(limit, 10)))
        ).all()
        lines = [f"找到 {len(rows)} 条历史记录：" if rows else "没有找到相关的历史研究记录。"]
        data = []
        for message, conversation in rows:
            snippet = message.content[:300]
            lines.append(f"- 《{conversation.title}》（{message.created_at:%Y-%m-%d}）：{snippet}")
            data.append({"conversation_id": conversation.id, "message_id": message.id, "snippet": snippet})
        return {"summary": "\n".join(lines), "citations": [], "data": {"messages": data}}


    # ---------------------------------------------------------------- V4 context tools
    def _project(self, project_id: str) -> Project:
        if project_id in self.exclude_ids:
            raise ToolError("该项目已被用户排除，不能读取")
        project = self.db.get(Project, project_id)
        if project is None or project.user_id != self.user.id:
            raise ToolError("未找到该研究项目，或无权访问")
        return project

    def _knowledge(self, knowledge_id: str) -> KnowledgeItem:
        if knowledge_id in self.exclude_ids:
            raise ToolError("该知识条目已被用户排除，不能读取")
        item = self.db.get(KnowledgeItem, knowledge_id)
        if item is None or item.user_id != self.user.id:
            raise ToolError("未找到该知识条目，或无权访问")
        return item

    def _artifact(self, artifact_id: str) -> AcademicArtifact:
        if artifact_id in self.exclude_ids:
            raise ToolError("该学术成果已被用户排除，不能读取")
        artifact = self.db.get(AcademicArtifact, artifact_id)
        if artifact is None or artifact.user_id != self.user.id:
            raise ToolError("未找到该学术成果，或无权访问")
        return artifact

    async def tool_search_knowledge(self, query: str, limit: int = 6, project_id: str | None = None) -> dict:
        if not self.auto_retrieval:
            raise ToolError("自动检索已关闭，请由用户显式选择知识条目")
        if project_id:
            self._project(project_id)
        hits = [
            (item, score)
            for item, score in research_context.search_knowledge(
                self.db, self.user, query, project_id=project_id, limit=max(1, min(limit, 12))
            )
            if item.id not in self.exclude_ids
        ]
        citations = []
        for index, (item, score) in enumerate(hits):
            citation = research_context.knowledge_citation(item, score)
            citation["key"] = f"C{index + 1}"
            citations.append(citation)
        summary = "\n".join(
            f"[C{index + 1}] [知识] {item.title}（{item.kind}，相关度 {score:.2f}）"
            f"\n{(item.content or '')[:600]}"
            for index, (item, score) in enumerate(hits)
        ) or "个人知识库中没有找到与问题相关的条目。"
        return {
            "summary": summary,
            "citations": citations,
            "data": {
                "items": [
                    {
                        "id": item.id, "title": item.title, "kind": item.kind,
                        "tags": item.tags or [], "project_id": item.project_id,
                        "source_paper_id": item.source_paper_id, "score": round(score, 4),
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                    for item, score in hits
                ]
            },
        }

    async def tool_read_knowledge(self, knowledge_id: str) -> dict:
        item = self._knowledge(knowledge_id)
        citation = research_context.knowledge_citation(item, 1.0)
        citation["key"] = "C1"
        return {
            "summary": f"[C1] [知识] {item.title}\n{item.content}",
            "citations": [citation],
            "data": {
                "id": item.id, "title": item.title, "content": item.content,
                "kind": item.kind, "tags": item.tags or [], "project_id": item.project_id,
                "source_paper_id": item.source_paper_id, "source_page": item.source_page,
            },
        }

    async def tool_get_project_context(self, project_id: str) -> dict:
        project = self._project(project_id)
        items = list(
            self.db.execute(
                select(ProjectItem)
                .where(ProjectItem.user_id == self.user.id, ProjectItem.project_id == project.id)
                .order_by(ProjectItem.created_at.asc())
            ).scalars().all()
        )
        notes = [item for item in items if item.kind in {"note", "笔记"}]
        citation = research_context.project_citation(project)
        citation["key"] = "C1"
        resource_lines = [f"- {item.kind}: {item.title}" for item in items[:30]]
        note_text = "\n".join(f"- {item.title}: {(item.content or '')[:600]}" for item in notes[:10])
        summary = (
            f"[C1] 项目「{project.name}」\n"
            f"目标：{project.goal or '未填写'}\n描述：{project.description or '未填写'}\n"
            f"进度：{project.progress}% · 状态：{project.status}\n"
            f"关联资源：\n" + ("\n".join(resource_lines) or "无") +
            ("\n\n项目笔记：\n" + note_text if note_text else "")
        )
        return {
            "summary": summary,
            "citations": [citation],
            "data": {
                "id": project.id, "name": project.name, "goal": project.goal,
                "description": project.description, "progress": project.progress,
                "status": project.status,
                "items": [
                    {"id": item.id, "kind": item.kind, "ref_id": item.ref_id, "title": item.title,
                     "content": (item.content or "")[:1200], "meta": item.meta or {}}
                    for item in items[:40]
                ],
            },
        }

    async def tool_search_project_resources(
        self, project_id: str, resource_type: str = "all", query: str = ""
    ) -> dict:
        project = self._project(project_id)
        items = list(
            self.db.execute(
                select(ProjectItem).where(
                    ProjectItem.user_id == self.user.id, ProjectItem.project_id == project.id
                ).order_by(ProjectItem.created_at.asc())
            ).scalars().all()
        )
        kinds = {"paper", "knowledge", "image", "figure", "artifact", "note", "笔记", "成果", "图片", "知识"}
        if resource_type != "all":
            kinds = {resource_type, "note" if resource_type == "note" else resource_type}
        lowered = query.lower().strip()
        citations: list[dict] = []
        rows: list[dict] = []
        for item in items:
            if item.kind not in kinds:
                continue
            if lowered and lowered not in ((item.title or "") + " " + (item.content or "")).lower():
                continue
            rows.append({"id": item.id, "kind": item.kind, "ref_id": item.ref_id, "title": item.title,
                         "content": (item.content or "")[:1000]})
            if item.kind == "paper" and item.ref_id:
                paper = self.db.get(Paper, item.ref_id)
                if paper and paper.user_id == self.user.id:
                    rows[-1]["title"] = paper.title
                    citation = {
                        "chunk_id": f"project-paper:{project.id}:{paper.id}",
                        "paper_id": paper.id, "paper_title": f"项目论文 · {paper.title}",
                        "page": 0, "section": "研究项目", "quote": (paper.abstract or paper.title)[:1200],
                        "resource_type": "paper", "resource_id": paper.id, "resource_title": paper.title,
                    }
                    citation["key"] = f"C{len(citations) + 1}"
                    citations.append(citation)
            elif item.kind in {"knowledge", "知识"} and item.ref_id:
                knowledge = self.db.get(KnowledgeItem, item.ref_id)
                if knowledge and knowledge.user_id == self.user.id:
                    citation = research_context.knowledge_citation(knowledge, 1.0)
                    citation["key"] = f"C{len(citations) + 1}"
                    citations.append(citation)
            elif item.kind in {"image", "figure", "图片"} and item.ref_id:
                figure = self.db.get(Figure, item.ref_id)
                if figure and figure.user_id == self.user.id:
                    citation = research_context.image_citation(figure)
                    citation["key"] = f"C{len(citations) + 1}"
                    citations.append(citation)
            elif item.kind in {"artifact", "成果"} and item.ref_id:
                artifact = self.db.get(AcademicArtifact, item.ref_id)
                if artifact and artifact.user_id == self.user.id:
                    citation = research_context.artifact_citation(artifact)
                    citation["key"] = f"C{len(citations) + 1}"
                    citations.append(citation)
        summary = "\n".join(
            f"[C{index + 1}] [{row['kind']}] {row['title']} {('- ' + row['content'][:250]) if row['content'] else ''}"
            for index, row in enumerate(rows[:20])
        ) or "项目中没有找到符合条件的资源。"
        return {"summary": summary, "citations": citations, "data": {"project_id": project.id, "items": rows}}

    async def tool_search_images(self, query: str = "", paper_id: str | None = None, limit: int = 6) -> dict:
        if not self.auto_retrieval:
            raise ToolError("自动检索已关闭，请由用户显式选择图片")
        paper_ids = None
        if paper_id:
            paper = self._paper(paper_id)
            paper_ids = [paper.id]
        elif self.scope_ids is not None:
            paper_ids = self.scope_ids
        figures = [
            figure for figure in research_context.search_images(
                self.db, self.user, query, paper_ids=paper_ids, limit=max(1, min(limit, 12))
            )
            if figure.id not in self.exclude_ids
        ]
        citations = []
        for index, figure in enumerate(figures):
            citation = research_context.image_citation(figure, self._paper_title(figure.paper_id))
            citation["key"] = f"C{index + 1}"
            citations.append(citation)
        summary = "\n".join(
            f"[C{index + 1}] [图片] {figure.caption or figure.kind}（论文 {figure.paper_id}，第 {figure.page_number} 页）"
            for index, figure in enumerate(figures)
        ) or "图像库中没有找到符合条件的图片。"
        return {
            "summary": summary,
            "citations": citations,
            "data": {"figures": [
                {"id": f.id, "paper_id": f.paper_id, "page": f.page_number, "kind": f.kind,
                 "caption": f.caption, "image_url": f"/api/figures/{f.id}/image",
                 "width": f.width, "height": f.height}
                for f in figures
            ]},
        }

    def _paper_title(self, paper_id: str) -> str | None:
        paper = self.db.get(Paper, paper_id)
        return paper.title if paper and paper.user_id == self.user.id else None

    async def _figure(self, image_id: str) -> Figure:
        if image_id in self.exclude_ids:
            raise ToolError("该图片已被用户排除，不能读取")
        figure = self.db.get(Figure, image_id)
        if figure is None or figure.user_id != self.user.id:
            raise ToolError("未找到该图片，或无权访问")
        if self.scope_ids is not None and figure.paper_id not in set(self.scope_ids):
            raise ToolError("该图片不在本次研究范围内")
        return figure

    async def tool_read_image(self, image_id: str) -> dict:
        figure = await self._figure(image_id)
        meta = research_context.image_metadata(figure)
        citation = research_context.image_citation(figure, self._paper_title(figure.paper_id))
        citation["key"] = "C1"
        if not meta.get("available"):
            return {
                "summary": f"[C1] 图片记录存在，但真实文件不可读：{meta.get('reason', '图片文件不存在')}。未进行视觉推断。",
                "citations": [citation],
                "data": {"image_id": figure.id, "metadata": meta, "vision_read": False},
            }
        return {
            "summary": (
                f"[C1] 已读取真实图片文件：{figure.caption or figure.kind}，"
                f"{meta.get('width', 0)}×{meta.get('height', 0)}，{meta.get('size_bytes', 0)} bytes。"
                "未进行视觉推断；如需语义分析，需要配置可用的视觉模型。"
            ),
            "citations": [citation],
            "data": {"image_id": figure.id, "metadata": meta, "vision_read": False},
        }

    async def tool_analyze_image(self, image_id: str, question: str = "解释这张图") -> dict:
        figure = await self._figure(image_id)
        citation = research_context.image_citation(figure, self._paper_title(figure.paper_id))
        citation["key"] = "C1"
        provider = self.vision_provider
        if not getattr(provider, "available", False):
            status = research_context.vision_status(self.config)
            return {
                "summary": (
                    f"无法完成真正的视觉分析：{getattr(provider, 'reason', status['reason'])} "
                    f"图片 {figure.caption or figure.kind} 已定位，图注/页码可作为上下文，"
                    "但不能把图注当作像素理解。"
                ),
                "citations": [citation],
                "data": {"image_id": figure.id, "vision": status, "question": question},
                "capability_limited": True,
            }
        asset = research_context.image_asset(figure)
        if asset is None:
            return {
                "summary": f"[C1] 图片 {figure.caption or figure.kind} 的真实文件不可读，未进行视觉分析。",
                "citations": [citation],
                "data": {"image_id": figure.id, "vision": {"available": True, "provider": provider.name}, "question": question},
                "capability_limited": True,
            }
        image_bytes, media_type = asset
        result = provider.analyze(
            image_bytes, media_type, question=question,
            caption=figure.caption, paper_title=self._paper_title(figure.paper_id),
        )
        figure.ai_explanation = result.analysis[:8000]
        self.db.commit()
        return {
            "summary": f"[C1] 视觉分析（{result.provider}/{result.model}，{result.elapsed_ms}ms）：{result.analysis}",
            "citations": [citation],
            "data": {
                "image_id": figure.id, "vision": {
                    "available": True, "provider": result.provider, "model": result.model,
                    "elapsed_ms": result.elapsed_ms, "media_type": media_type,
                },
                "question": question,
            },
        }

    async def tool_list_artifacts(self, kind: str = "", project_id: str | None = None, limit: int = 8) -> dict:
        if not self.auto_retrieval:
            raise ToolError("自动检索已关闭，请由用户显式选择成果")
        if project_id:
            self._project(project_id)
        artifacts = [
            artifact for artifact in research_context.search_artifacts(
                self.db, self.user, "", project_id=project_id, limit=max(1, min(limit, 20))
            )
            if artifact.id not in self.exclude_ids
        ]
        if kind:
            artifacts = [artifact for artifact in artifacts if artifact.kind == kind]
        citations = []
        for index, artifact in enumerate(artifacts):
            citation = research_context.artifact_citation(artifact)
            citation["key"] = f"C{index + 1}"
            citations.append(citation)
        summary = "\n".join(
            f"[C{index + 1}] [成果] {artifact.title}（{artifact.kind}，{artifact.quality_status}，{artifact.quality_score} 分）"
            for index, artifact in enumerate(artifacts)
        ) or "没有找到已有学术成果。"
        return {"summary": summary, "citations": citations, "data": {"artifacts": [
            {"id": a.id, "title": a.title, "kind": a.kind, "quality_status": a.quality_status,
             "quality_score": a.quality_score, "paper_ids": a.paper_ids or [],
             "created_at": a.created_at.isoformat() if a.created_at else None}
            for a in artifacts
        ]}}

    async def tool_read_artifact(self, artifact_id: str) -> dict:
        artifact = self._artifact(artifact_id)
        citation = research_context.artifact_citation(artifact)
        citation["key"] = "C1"
        return {
            "summary": f"[C1] [成果] {artifact.title}\n{artifact.content[:3500]}",
            "citations": [citation],
            "data": {"id": artifact.id, "title": artifact.title, "content": artifact.content,
                     "kind": artifact.kind, "quality_status": artifact.quality_status,
                     "quality_score": artifact.quality_score, "paper_ids": artifact.paper_ids or []},
        }

    async def tool_generate_artifact(
        self, kind: str, title: str | None = None, scope_type: str = "papers",
        scope_id: str | None = None, paper_ids: list[str] | None = None,
        knowledge_ids: list[str] | None = None, image_ids: list[str] | None = None,
    ) -> dict:
        args = {"kind": kind, "title": title, "scope_type": scope_type, "scope_id": scope_id,
                "paper_ids": paper_ids or [], "knowledge_ids": knowledge_ids or [],
                "image_ids": image_ids or []}
        guard = self._guard("generate_artifact", args, "生成学术成果", f"{kind} · {title or ''}")
        if guard:
            return guard
        from . import artifacts as artifact_service
        artifact, report = await artifact_service.generate_artifact(
            self.db, self.user, kind=kind, scope_type=scope_type, scope_id=scope_id,
            paper_ids=paper_ids, title=title, config=self.config,
        )
        source_knowledge = [self._knowledge(item) for item in (knowledge_ids or []) if item]
        source_images = [self.db.get(Figure, item) for item in (image_ids or []) if item]
        source_images = [figure for figure in source_images if figure is not None and figure.user_id == self.user.id]
        source_citations = []
        source_lines = []
        for index, item in enumerate(source_knowledge):
            source_citations.append(research_context.knowledge_citation(item, 1.0))
            source_citations[-1]["key"] = f"K{index + 1}"
            source_lines.append(f"- [知识 K{index + 1}] {item.title}（{item.id}）")
        for index, figure in enumerate(source_images):
            source_citations.append(research_context.image_citation(figure, self._paper_title(figure.paper_id)))
            source_citations[-1]["key"] = f"I{index + 1}"
            source_lines.append(f"- [图片 I{index + 1}] {figure.caption or figure.kind}（第 {figure.page_number} 页，{figure.id}）")
        if source_lines:
            artifact.content = (artifact.content or "") + "\n\n## 跨模块上下文来源\n\n" + "\n".join(source_lines)
            artifact.citations = list(artifact.citations or []) + source_citations
            self.db.commit()
        if scope_type == "project" and scope_id:
            project = self._project(scope_id)
            exists = self.db.execute(
                select(ProjectItem).where(
                    ProjectItem.user_id == self.user.id,
                    ProjectItem.project_id == project.id,
                    ProjectItem.kind == "artifact",
                    ProjectItem.ref_id == artifact.id,
                )
            ).scalar_one_or_none()
            if exists is None:
                self.db.add(ProjectItem(
                    project_id=project.id, user_id=self.user.id, kind="artifact",
                    ref_id=artifact.id, title=artifact.title,
                ))
                self.db.commit()
        citation = research_context.artifact_citation(artifact)
        citation["key"] = "C1"
        return {
            "summary": f"[C1] 已生成学术成果「{artifact.title}」，质量状态 {report.status}（{report.score} 分）。",
            "citations": [citation],
            "data": {"artifact_id": artifact.id, "quality": {"status": report.status, "score": report.score, "summary": report.summary, "issues": report.issues}},
        }

    async def tool_check_artifact(self, artifact_id: str) -> dict:
        artifact = self._artifact(artifact_id)
        from . import artifacts as artifact_service
        report = artifact_service.check_artifact(self.db, artifact)
        record = ArtifactQualityReport(
            user_id=self.user.id, artifact_id=artifact.id, status=report["status"],
            score=report["score"], issues=report["issues"], summary=report["summary"], checked_at=utcnow(),
        )
        self.db.add(record)
        artifact.quality_status = report["status"]
        artifact.quality_score = report["score"]
        self.db.commit()
        citation = research_context.artifact_citation(artifact)
        citation["key"] = "C1"
        issues = "\n".join(
            f"- [{issue.get('severity')}] {issue.get('location')}: {issue.get('message')}"
            for issue in report["issues"][:12]
        )
        return {
            "summary": f"[C1] 成果「{artifact.title}」质量检查：{report['summary']}\n{issues}",
            "citations": [citation],
            "data": {"artifact_id": artifact.id, "quality": report},
        }

    async def tool_export_artifact(self, artifact_id: str, format: str = "md") -> dict:
        artifact = self._artifact(artifact_id)
        guard = self._guard(
            "export_artifact", {"artifact_id": artifact_id, "format": format},
            "导出学术成果", f"{artifact.title} ({format})",
        )
        if guard:
            return guard
        from . import artifacts as artifact_service
        record = artifact_service.export_artifact(self.db, self.user, artifact, format)
        return {
            "summary": f"已导出「{artifact.title}」为 {format}：{record.filename}",
            "citations": [],
            "data": {"export_id": record.id, "filename": record.filename},
        }


def compact_tool_payload(result: dict, limit: int = 6000) -> str:
    payload = {
        "summary": result.get("summary", "")[:limit],
        "citations": [
            {k: c.get(k) for k in ("key", "paper_title", "page", "section")}
            for c in (result.get("citations") or [])[:12]
        ],
        "pending": bool(result.get("pending")),
    }
    return json.dumps(payload, ensure_ascii=False)[:limit]
