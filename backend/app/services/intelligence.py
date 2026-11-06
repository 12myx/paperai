"""P5 Research Intelligence: landscape, trends, connections, opportunities.

Scope is always explicit. The first stage only analyses the user's library
(optionally one project/collection), never external literature. Local mode is
deterministic and labelled; generative mode produces structured JSON but every
claim must carry evidence keys.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Collection,
    CollectionPaper,
    IntelligenceReport,
    KnowledgeItem,
    Paper,
    Project,
    ProjectItem,
    User,
)
from .llm import LLMClient, LLMError, ModelConfig
from .multipaper import DIMENSIONS, _facet_citations, ensure_facets
from .retrieval import STOPWORDS

SCOPE_TYPES = {"all", "papers", "collection", "project"}
ALL_SCOPE_LIMIT = 120


class IntelligenceError(ValueError):
    pass


# ------------------------------------------------------------------ scope

def resolve_scope(
    db: Session,
    user: User,
    scope_type: str,
    scope_id: str | None = None,
    paper_ids: list[str] | None = None,
) -> tuple[list[Paper], dict]:
    scope_type = scope_type if scope_type in SCOPE_TYPES else "all"
    label = "全部资料库"
    selected: list[Paper] = []
    all_total = 0

    if scope_type == "project":
        project = db.get(Project, scope_id or "")
        if project is None or project.user_id != user.id:
            raise IntelligenceError("项目不存在或无权访问")
        label = f"项目 · {project.name}"
        refs = db.execute(
            select(ProjectItem.ref_id).where(
                ProjectItem.project_id == project.id,
                ProjectItem.kind == "paper",
                ProjectItem.user_id == user.id,
            )
        ).scalars().all()
        ids = [ref for ref in refs if ref]
        if ids:
            selected = list(
                db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all()
            )
    elif scope_type == "collection":
        collection = db.get(Collection, scope_id or "")
        if collection is None or collection.user_id != user.id:
            raise IntelligenceError("合集不存在或无权访问")
        label = f"合集 · {collection.name}"
        ids = db.execute(
            select(CollectionPaper.paper_id).where(CollectionPaper.collection_id == collection.id)
        ).scalars().all()
        if ids:
            selected = list(
                db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all()
            )
    elif scope_type == "papers":
        ids = [paper_id for paper_id in dict.fromkeys(paper_ids or []) if paper_id]
        label = f"已选 {len(ids)} 篇论文"
        if ids:
            selected = list(
                db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all()
            )
    else:
        all_total = db.execute(
            select(func.count(Paper.id)).where(Paper.user_id == user.id, Paper.status == "ready")
        ).scalar() or 0
        selected = list(
            db.execute(
                select(Paper)
                .where(Paper.user_id == user.id, Paper.status == "ready")
                .order_by(Paper.created_at.desc())
                .limit(ALL_SCOPE_LIMIT)
            ).scalars().all()
        )
        if all_total > ALL_SCOPE_LIMIT:
            label = f"最近 {ALL_SCOPE_LIMIT} 篇（资料库共 {all_total} 篇）"

    selected = [paper for paper in selected if paper.status == "ready"]
    if not selected:
        raise IntelligenceError("该研究范围内没有已解析的论文")
    selected.sort(key=lambda paper: (paper.year or 0, paper.title))
    years = sorted({paper.year for paper in selected if paper.year})
    unknown_years = sum(1 for paper in selected if not paper.year)
    scope = {
        "type": scope_type,
        "id": scope_id,
        "label": label,
        "paper_count": len(selected),
        "years": years,
        "year_min": years[0] if years else None,
        "year_max": years[-1] if years else None,
        "unknown_years": unknown_years,
        "boundary": "仅基于资料库内论文，不代表全球学术领域",
        "external_data": False,
        "limited": scope_type == "all" and all_total > ALL_SCOPE_LIMIT,
    }
    return selected, scope


# ------------------------------------------------------------------ helpers

def _cell(facet, field: str) -> dict:
    return ((facet.fields or {}).get(field) or {}) if facet else {}


def _citation_index(citations: list[dict]) -> dict[tuple[str, str], dict]:
    return {(citation["paper_id"], citation.get("chunk_id")): citation for citation in citations if citation.get("chunk_id")}


def _item_from_cell(facet, paper: Paper, field: str, citations: dict) -> dict | None:
    cell = _cell(facet, field)
    if not cell or not cell.get("text") or cell.get("text") == "未提及":
        return None
    citation = citations.get((paper.id, cell.get("chunk_id")))
    return {
        "text": cell.get("text"),
        "quote": cell.get("quote"),
        "page": cell.get("page"),
        "section": cell.get("section"),
        "paper_id": paper.id,
        "paper_title": paper.title,
        "year": paper.year,
        "evidence_id": cell.get("evidence_id"),
        "evidence_key": citation.get("key") if citation else None,
        "verified": bool(cell.get("verified")),
    }


def _dedupe_items(items: list[dict], limit: int = 8) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = re.sub(r"\s+", " ", (item.get("text") or "").casefold())[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _save_report(
    db: Session,
    user: User,
    *,
    kind: str,
    scope: dict,
    papers: list[Paper],
    data: dict,
    citations: list[dict],
    local: bool,
    model: str | None,
) -> IntelligenceReport:
    report = IntelligenceReport(
        user_id=user.id,
        kind=kind,
        scope_type=scope["type"],
        scope_id=scope.get("id"),
        scope_label=scope["label"],
        paper_ids=[paper.id for paper in papers],
        data=data,
        citations=citations,
        local=local,
        model=model,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _source_signature(papers: list[Paper], facets: list) -> str:
    parts = [
        f"{paper.id}:{paper.updated_at}:{paper.title}:{(paper.meta or {}).get('chunk_count', '')}"
        for paper in papers
    ]
    for facet in sorted(facets, key=lambda item: item.paper_id):
        parts.append(
            f"{facet.paper_id}:{facet.updated_at}:"
            + json.dumps(facet.fields or {}, sort_keys=True, default=str, ensure_ascii=False)
        )
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _latest_report(db: Session, user: User, kind: str, scope: dict, signature: str | None = None) -> IntelligenceReport | None:
    report = db.execute(
        select(IntelligenceReport)
        .where(
            IntelligenceReport.user_id == user.id,
            IntelligenceReport.kind == kind,
            IntelligenceReport.scope_type == scope["type"],
            IntelligenceReport.scope_id.is_(None)
            if scope.get("id") is None
            else IntelligenceReport.scope_id == scope.get("id"),
        )
        .order_by(IntelligenceReport.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if report is not None and signature is not None:
        if (report.data or {}).get("_source_signature") != signature:
            return None
    return report


# ------------------------------------------------------------------ landscape

def _landscape_items(papers: list[Paper], facets: list, citations: list[dict]) -> dict:
    index = _citation_index(citations)
    by_paper = {paper.id: paper for paper in papers}
    questions, methods, challenges, future = [], [], [], []
    for facet in facets:
        paper = by_paper.get(facet.paper_id)
        if paper is None:
            continue
        question = _item_from_cell(facet, paper, "research_question", index)
        method = _item_from_cell(facet, paper, "method", index)
        limitation = _item_from_cell(facet, paper, "limitations", index)
        if question:
            questions.append(question)
        if method:
            methods.append(method)
        if limitation:
            challenges.append(limitation)
            future.append({**limitation, "text": "围绕该局限设计验证：" + (limitation.get("text") or "")[:120]})
    return {
        "core_questions": _dedupe_items(questions, 8),
        "technical_routes": _dedupe_items(methods, 8),
        "key_methods": _dedupe_items(methods, 8),
        "challenges": _dedupe_items(challenges, 8),
        "future_directions": _dedupe_items(future, 8),
    }


def build_landscape(db: Session, user: User, papers: list[Paper], facets: list, scope: dict, config: ModelConfig | None) -> IntelligenceReport:
    citations, context = _facet_citations(db, papers, facets)
    local_data = _landscape_items(papers, facets, citations)
    years = scope.get("years") or []
    overview = (
        f"资料库内 {len(papers)} 篇论文，覆盖 {scope.get('year_min') or '未知'}–{scope.get('year_max') or '未知'} 年。"
        f"以下结构来自每篇论文的六维画像与原文证据；这是资料库范围的研究全景，不是全球领域结论。"
    )
    representative = [
        {
            "paper_id": paper.id,
            "title": paper.title,
            "year": paper.year,
            "method": (_cell(next((f for f in facets if f.paper_id == paper.id), None), "method") or {}).get("text") or "未提及",
            "findings": (_cell(next((f for f in facets if f.paper_id == paper.id), None), "findings") or {}).get("text") or "未提及",
        }
        for paper in papers
    ]
    data = {
        "overview": overview,
        "core_questions": local_data["core_questions"],
        "technical_routes": local_data["technical_routes"],
        "key_methods": local_data["key_methods"],
        "representative_papers": representative,
        "challenges": local_data["challenges"],
        "future_directions": local_data["future_directions"],
        "local": True,
        "note": "本地抽取模式：只归纳真实原文画像，不生成领域判断。",
        "scope": scope,
    }
    local = True
    model_name = None

    if config is not None:
        prompt = (
            "基于以下论文六维画像与编号证据，生成资料库范围的研究全景。只输出 JSON：\n"
            "{\"overview\":\"\",\"core_questions\":[{\"text\":\"\",\"evidence_keys\":[\"C1\"]}],"
            "\"technical_routes\":[{\"text\":\"\",\"evidence_keys\":[\"C1\"]}],"
            "\"key_methods\":[{\"text\":\"\",\"evidence_keys\":[\"C1\"]}],"
            "\"challenges\":[{\"text\":\"\",\"evidence_keys\":[\"C1\"]}],"
            "\"future_directions\":[{\"text\":\"\",\"evidence_keys\":[\"C1\"]}]}。\n"
            "规则：每条必须带 evidence_keys；没有证据的条目不要输出；不得声称覆盖全球领域；必须写明这是资料库范围。\n\n"
            + context
        )
        try:
            response = LLMClient(config).complete([{"role": "user", "content": prompt}], temperature=0.25, max_tokens=1800)
            payload = _parse_json(response.get("content") or "")
            if payload:
                by_key = {citation["key"]: citation for citation in citations}
                converted = {}
                used = False
                for field in ("core_questions", "technical_routes", "key_methods", "challenges", "future_directions"):
                    items = []
                    for item in payload.get(field) or []:
                        if not isinstance(item, dict):
                            continue
                        keys = [key for key in (item.get("evidence_keys") or []) if key in by_key]
                        if not keys:
                            continue
                        citation = by_key[keys[0]]
                        items.append(
                            {
                                "text": str(item.get("text") or "")[:400],
                                "quote": citation.get("quote"),
                                "page": citation.get("page"),
                                "section": citation.get("section"),
                                "paper_id": citation.get("paper_id"),
                                "paper_title": citation.get("paper_title"),
                                "year": citation.get("paper_year"),
                                "evidence_key": citation.get("key"),
                                "verified": bool(citation.get("verified")),
                            }
                        )
                    converted[field] = items[:8]
                    used = used or bool(items)
                if used:
                    data.update(converted)
                    if payload.get("overview"):
                        data["overview"] = str(payload["overview"])[:1200]
                    data["local"] = False
                    data["note"] = "生成式研究全景；每条带编号证据，范围仍限于资料库。"
                    local = False
                    model_name = config.model
        except LLMError:
            data["note"] = "模型调用失败，已回退为本地抽取全景。"

    data["_source_signature"] = _source_signature(papers, facets)
    report = _save_report(
        db, user, kind="landscape", scope=scope, papers=papers, data=data,
        citations=citations, local=local, model=model_name,
    )
    return report


# ------------------------------------------------------------------ trends

def _keyword_terms(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", (text or "").lower())
    return [token for token in tokens if token not in STOPWORDS and token not in {"paper", "using", "used", "approach", "method"}]


def build_trends(db: Session, user: User, papers: list[Paper], facets: list, scope: dict, config: ModelConfig | None) -> IntelligenceReport:
    citations, _context = _facet_citations(db, papers, facets)
    year_counts: Counter = Counter()
    keyword_by_year: dict[int, Counter] = defaultdict(Counter)
    method_counts: Counter = Counter()
    for paper in papers:
        if paper.year:
            year_counts[paper.year] += 1
        facet = next((item for item in facets if item.paper_id == paper.id), None)
        if facet is None:
            continue
        method = _cell(facet, "method").get("text") or ""
        findings = _cell(facet, "findings").get("text") or ""
        question = _cell(facet, "research_question").get("text") or ""
        if method and method != "未提及":
            method_counts[method[:140]] += 1
        if paper.year:
            for term in _keyword_terms(" ".join([paper.title, method, findings, question])):
                keyword_by_year[paper.year][term] += 1
    years_sorted = sorted(year_counts)
    keyword_trends = [
        {"year": year, "terms": [{"term": term, "count": count} for term, count in keyword_by_year[year].most_common(8)]}
        for year in years_sorted
    ]
    observations = []
    if years_sorted:
        peak_year = max(year_counts, key=year_counts.get)
        observations.append(f"资料库中 {peak_year} 年样本最多（{year_counts[peak_year]} 篇）。")
    if method_counts:
        method, count = method_counts.most_common(1)[0]
        observations.append(f"方法文本出现最多的是“{method[:80]}”（{count} 篇）。")
    observations.append("以上仅为资料库内样本统计，不代表全球研究趋势，也不等同于学术热点。")
    data = {
        "year_counts": [{"year": year, "count": year_counts[year]} for year in years_sorted],
        "unknown_year_count": sum(1 for paper in papers if not paper.year),
        "keyword_trends": keyword_trends,
        "method_counts": [{"method": method, "count": count} for method, count in method_counts.most_common(10)],
        "observations": observations,
        "local": True,
        "note": "本地统计：仅基于资料库内真实出版年份与论文画像词频；样本量小或年份缺失时请勿过度解读，不代表全球趋势。",
        "scope": scope,
    }
    data["_source_signature"] = _source_signature(papers, facets)
    report = _save_report(
        db, user, kind="trends", scope=scope, papers=papers, data=data,
        citations=citations, local=True, model=None,
    )
    return report


# ------------------------------------------------------------------ connections

def _slug(text: str) -> str:
    return hashlib.sha1(text.strip().casefold().encode("utf-8")).hexdigest()[:10]


def _short(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rsplit(" ", 1)[0] or cleaned[:limit]
    return cut.rstrip(" ,.;:") + "…"


def build_connections(db: Session, user: User, papers: list[Paper], facets: list, scope: dict, config: ModelConfig | None) -> IntelligenceReport:
    citations, _context = _facet_citations(db, papers, facets)
    index = _citation_index(citations)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_seen: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, node_type: str, label: str, meta: dict | None = None) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "type": node_type, "label": label[:120], "meta": meta or {}}

    def add_edge(source: str, target: str, relation: str, basis: dict | None = None) -> None:
        key = (source, target, relation)
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append({"id": f"{source}->{target}:{relation}", "source": source, "target": target, "relation": relation, "basis": basis or {}})

    by_paper = {paper.id: paper for paper in papers}
    for paper in papers:
        add_node(f"paper:{paper.id}", "paper", paper.title, {"paper_id": paper.id, "year": paper.year})

    for facet in facets:
        paper = by_paper.get(facet.paper_id)
        if paper is None:
            continue
        for field, node_type, relation, prefix in (
            ("method", "method", "uses_method", "方法"),
            ("dataset", "dataset", "uses_dataset", "数据集"),
            ("research_question", "question", "studies", "问题"),
        ):
            cell = _cell(facet, field)
            text = (cell.get("text") or "").strip()
            if not text or text == "未提及":
                continue
            node_id = f"{node_type}:{_slug(text)}"
            add_node(node_id, node_type, text[:120], {"field": field})
            citation = index.get((paper.id, cell.get("chunk_id")))
            add_edge(
                f"paper:{paper.id}", node_id, relation,
                {
                    "page": cell.get("page"),
                    "quote": (citation or {}).get("quote") or cell.get("quote"),
                    "paper_id": paper.id,
                    "evidence_id": cell.get("evidence_id"),
                },
            )

    knowledge = db.execute(
        select(KnowledgeItem).where(
            KnowledgeItem.user_id == user.id,
            KnowledgeItem.source_paper_id.in_([paper.id for paper in papers]),
        )
    ).scalars().all()
    for item in knowledge:
        node_id = f"knowledge:{item.id}"
        add_node(node_id, "knowledge", item.title, {"kind": item.kind})
        add_edge(
            node_id,
            f"paper:{item.source_paper_id}",
            "derived_from",
            {"quote": item.source_quote, "page": item.source_page, "knowledge_id": item.id},
        )

    counts: Counter = Counter(node["type"] for node in nodes.values())
    data = {
        "nodes": list(nodes.values()),
        "edges": edges,
        "counts": dict(counts),
        "local": True,
        "note": "节点与边均由论文画像、个人知识与来源关系生成；没有来源的边不会出现。",
        "scope": scope,
    }
    data["_source_signature"] = _source_signature(papers, facets)
    report = _save_report(
        db, user, kind="connections", scope=scope, papers=papers, data=data,
        citations=citations, local=True, model=None,
    )
    return report


# ------------------------------------------------------------------ opportunities

def _local_opportunities(papers: list[Paper], facets: list, citations: list[dict]) -> list[dict]:
    index = _citation_index(citations)
    by_paper = {paper.id: paper for paper in papers}
    grouped: dict[str, dict] = {}
    for facet in facets:
        paper = by_paper.get(facet.paper_id)
        if paper is None:
            continue
        limitation = _item_from_cell(facet, paper, "limitations", index)
        if not limitation:
            continue
        gap_text = limitation.get("text") or ""
        key = re.sub(r"\s+", " ", gap_text.casefold()).strip()[:160]
        if key in grouped:
            grouped[key]["related_papers"].append({"paper_id": paper.id, "title": paper.title})
            continue
        title = "补足：" + _short(gap_text, 64)
        grouped[key] = {
            "id": _slug(paper.id + title),
            "title": title,
            "background": f"《{paper.title}》（{paper.year or '年份未知'}）在原文中指出了这一局限。",
            "related_papers": [{"paper_id": paper.id, "title": paper.title}],
            "evidence": limitation,
            "existing_gap": gap_text,
            "why": "该局限由论文原文直接指出；是否值得研究需要结合领域现状判断。",
            "entry_point": "从该局限出发设计对照实验：保持原文数据集与指标不变，只改变与局限相关的变量。",
            "experiment_plan": "复用原文数据集与评价指标，设置原文基线，增加针对该局限的消融/对照实验，并报告显著性。",
            "difficulty": "待评估",
            "knowledge_needed": "需要掌握原文方法、数据集与指标对应的实验设置。",
            "risks": "仅为基于原文局限的启发式建议；不保证学术创新性，也不保证可发表。",
            "ai_generated": False,
            "heuristic": True,
        }
    results = list(grouped.values())
    for item in results:
        if len(item["related_papers"]) > 1:
            item["background"] = f"{len(item['related_papers'])} 篇论文在原文中指出同一局限。"
    return results[:8]


def build_opportunities(db: Session, user: User, papers: list[Paper], facets: list, scope: dict, config: ModelConfig | None) -> IntelligenceReport:
    citations, context = _facet_citations(db, papers, facets)
    opportunities = _local_opportunities(papers, facets, citations)
    data = {
        "opportunities": opportunities,
        "local": True,
        "note": "本地模式：从论文明确写出的局限生成候选方向，属于启发式建议，不是学术创新性判断。",
        "scope": scope,
    }
    local = True
    model_name = None

    if config is not None:
        prompt = (
            "基于以下论文画像与编号证据，提出可执行的研究机会。只输出 JSON："
            "{\"opportunities\":[{\"title\":\"\",\"background\":\"\",\"existing_gap\":\"\","
            "\"entry_point\":\"\",\"experiment_plan\":\"\",\"difficulty\":\"unknown|low|medium|high\","
            "\"knowledge_needed\":\"\",\"risks\":\"\",\"evidence_keys\":[\"C1\"]}]}。\n"
            "规则：每条必须有原文证据；不得声称保证创新性或可发表；区分已知局限与你的建议；"
            "不确定时写 unknown。\n\n" + context
        )
        try:
            response = LLMClient(config).complete([{"role": "user", "content": prompt}], temperature=0.35, max_tokens=1800)
            payload = _parse_json(response.get("content") or "")
            if payload:
                by_key = {citation["key"]: citation for citation in citations}
                generated = []
                for item in payload.get("opportunities") or []:
                    if not isinstance(item, dict):
                        continue
                    keys = [key for key in (item.get("evidence_keys") or []) if key in by_key]
                    if not keys:
                        continue
                    citation = by_key[keys[0]]
                    generated.append(
                        {
                            "id": _slug(str(item.get("title") or "") + citation["key"]),
                            "title": str(item.get("title") or "")[:200],
                            "background": str(item.get("background") or "")[:800],
                            "related_papers": [{"paper_id": citation["paper_id"], "title": citation["paper_title"]}],
                            "evidence": {
                                "text": (item.get("existing_gap") or "")[:400],
                                "quote": citation.get("quote"),
                                "page": citation.get("page"),
                                "section": citation.get("section"),
                                "paper_id": citation.get("paper_id"),
                                "paper_title": citation.get("paper_title"),
                                "evidence_key": citation.get("key"),
                                "verified": bool(citation.get("verified")),
                            },
                            "existing_gap": str(item.get("existing_gap") or "")[:600],
                            "why": "基于所引证据的 AI 建议；需人工核验。",
                            "entry_point": str(item.get("entry_point") or "")[:600],
                            "experiment_plan": str(item.get("experiment_plan") or "")[:800],
                            "difficulty": str(item.get("difficulty") or "unknown"),
                            "knowledge_needed": str(item.get("knowledge_needed") or "")[:500],
                            "risks": str(item.get("risks") or "需验证创新性与可行性")[:500],
                            "ai_generated": True,
                            "heuristic": False,
                        }
                    )
                if generated:
                    opportunities = generated[:8]
                    data["opportunities"] = opportunities
                    data["local"] = False
                    data["note"] = "生成式研究建议；每条带证据，但不保证创新性或可发表。"
                    local = False
                    model_name = config.model
        except LLMError:
            data["note"] = "模型调用失败，已回退为本地启发式建议。"

    data["_source_signature"] = _source_signature(papers, facets)
    report = _save_report(
        db, user, kind="opportunities", scope=scope, papers=papers, data=data,
        citations=citations, local=local, model=model_name,
    )
    return report


# ------------------------------------------------------------------ orchestration

def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


async def build_overview(
    db: Session,
    user: User,
    *,
    scope_type: str,
    scope_id: str | None,
    paper_ids: list[str] | None,
    config: ModelConfig | None,
    force: bool = False,
) -> dict:
    papers, scope = resolve_scope(db, user, scope_type, scope_id, paper_ids)
    facets = await ensure_facets(db, user, papers, config, force=force)
    builders = {
        "landscape": lambda: build_landscape(db, user, papers, facets, scope, config),
        "trends": lambda: build_trends(db, user, papers, facets, scope, config),
        "connections": lambda: build_connections(db, user, papers, facets, scope, config),
        "opportunities": lambda: build_opportunities(db, user, papers, facets, scope, config),
    }
    reports = {}
    current_ids = {paper.id for paper in papers}
    signature = _source_signature(papers, facets)
    for kind, builder in builders.items():
        cached = None if force else _latest_report(db, user, kind, scope, signature)
        if cached is not None and set(cached.paper_ids or []) != current_ids:
            cached = None
        report = cached or builder()
        reports[kind] = report

    return {
        "scope": scope,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports": {
            kind: {
                "id": report.id,
                "kind": report.kind,
                "scope_type": report.scope_type,
                "scope_id": report.scope_id,
                "scope_label": report.scope_label,
                "data": report.data,
                "citations": report.citations,
                "local": report.local,
                "model": report.model,
                "created_at": report.created_at.isoformat() + "Z" if report.created_at else None,
            }
            for kind, report in reports.items()
        },
    }