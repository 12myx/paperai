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
    Annotation,
    Chunk,
    Conversation,
    ExportRecord,
    Figure,
    KnowledgeItem,
    Message,
    Paper,
    User,
)
from . import analysis
from .export import build_export
from .llm import LLMClient, LLMError, ModelConfig, system_prompt
from .rag import search as rag_search
from .storage import safe_filename, storage

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
    ) -> None:
        self.db = db
        self.user = user
        self.config = config
        self.scope_ids = scope_ids
        self.allow_writes = allow_writes
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
            return None if self.scope_ids is None else list(self.scope_ids)
        if self.scope_ids is None:
            return list(dict.fromkeys(requested))
        allowed = set(self.scope_ids)
        return [paper_id for paper_id in dict.fromkeys(requested) if paper_id in allowed]

    def _papers(self, paper_ids: list[str] | None) -> list[Paper]:
        ids = self._scoped_ids(paper_ids)
        query = select(Paper).where(Paper.user_id == self.user.id)
        if ids is not None:
            query = query.where(Paper.id.in_(ids))
        return list(self.db.execute(query.order_by(Paper.created_at)).scalars().all())

    def _paper(self, paper_id: str) -> Paper:
        paper = self.db.get(Paper, paper_id)
        if paper is None or paper.user_id != self.user.id:
            raise ToolError("未找到该论文，或无权访问")
        if self.scope_ids is not None and paper.id not in set(self.scope_ids):
            raise ToolError("该论文不在本次研究范围内")
        return paper

    def _guard(self, name: str, args: dict, label: str, preview: str) -> dict:
        if self.allow_writes:
            return {}
        return {
            "pending": True,
            "action": {"tool": name, "args": args, "label": label, "preview": preview[:1200]},
            "summary": f"已生成待确认操作：{label}。请用户在界面中确认后执行。",
            "citations": [],
            "data": {},
        }

    # ------------------------------------------------------------------ tools
    async def run(self, name: str, args: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ToolError(f"未知工具：{name}")
        try:
            result = await handler(**args)
        except TypeError as exc:
            raise ToolError(f"工具参数错误：{exc}") from exc
        return self._register(result)

    async def tool_search_papers(self, query: str, limit: int = 8) -> dict:
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
        force: bool = False,
    ) -> dict:
        from .knowledge import DUPLICATE_THRESHOLD, find_duplicate
        candidate, score = find_duplicate(self.db, self.user, title, content)
        if candidate is not None and score >= DUPLICATE_THRESHOLD and not force:
            args = {"title": title, "content": content, "kind": kind, "paper_id": paper_id, "page": page, "tags": tags or [], "force": True}
            guard = self._guard(
                "save_knowledge",
                args,
                "保存相似知识（需确认）",
                f"与「{candidate.title}」相似度 {score:.0%}。确认后会仍然创建新条目。\n\n{content}",
            )
            if guard:
                return guard
        guard = self._guard("save_knowledge", {"title": title, "content": content, "kind": kind, "paper_id": paper_id, "page": page, "tags": tags or []}, "保存到知识库", content)
        if guard:
            return guard
        if paper_id:
            self._paper(paper_id)
        item = KnowledgeItem(
            user_id=self.user.id, title=title[:390], content=content, kind=kind,
            source_paper_id=paper_id, source_page=page, tags=tags or [],
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
        statement = select(Figure).where(Figure.user_id == self.user.id)
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