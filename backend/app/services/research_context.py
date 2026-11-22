"""Unified research context resolver for papers, knowledge, projects, images and artifacts.

The resolver is deliberately read-only and validates every resource against the
authenticated user before it can enter an Agent prompt or tool result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import AcademicArtifact, Figure, KnowledgeItem, Paper, Project, ProjectItem, User
from .knowledge import hybrid_search
from .storage import storage

RESOURCE_TYPES = {"paper", "knowledge", "image", "artifact", "project"}
IMAGE_WORDS = ("图", "图片", "图表", "figure", "fig.", "table", "表")
ARTIFACT_WORDS = ("成果", "报告", "综述", "开题", "计划", "artifact", "report", "review", "proposal")
PROJECT_WORDS = ("项目", "课题", "研究目标", "project", "proposal")


@dataclass
class UnifiedResearchContext:
    user: User
    question: str
    project: Project | None = None
    project_items: list[ProjectItem] = field(default_factory=list)
    project_notes: list[ProjectItem] = field(default_factory=list)
    knowledge: list[KnowledgeItem] = field(default_factory=list)
    knowledge_scores: dict[str, float] = field(default_factory=dict)
    images: list[Figure] = field(default_factory=list)
    artifacts: list[AcademicArtifact] = field(default_factory=list)
    paper_titles: dict[str, str] = field(default_factory=dict)
    excluded_ids: set[str] = field(default_factory=set)

    def prompt_block(self) -> str:
        """Compact, budgeted context for the model. Never include unrelated rows."""
        parts: list[str] = []
        if self.project:
            parts.append(
                "## 当前研究项目\n"
                f"名称：{self.project.name}\n"
                f"目标：{(self.project.goal or '未填写')[:1800]}\n"
                f"描述：{(self.project.description or '未填写')[:1800]}\n"
                f"进度：{self.project.progress}%"
            )
        if self.project_notes:
            notes = "\n".join(f"- {item.title}: {(item.content or '')[:500]}" for item in self.project_notes[:8])
            parts.append("## 项目笔记\n" + notes)
        if self.knowledge:
            rows = []
            for item in self.knowledge[:6]:
                source = self.paper_titles.get(item.source_paper_id or "", "")
                rows.append(
                    f"- [知识 {item.id}] {item.title}（{item.kind}）"
                    + (f"；来源论文：{source}" if source else "")
                    + f"\n  {(item.content or '')[:900]}"
                )
            parts.append("## 个人知识库命中\n" + "\n".join(rows))
        if self.images:
            rows = []
            for figure in self.images[:5]:
                rows.append(
                    f"- [图片 {figure.id}] 论文：{self.paper_titles.get(figure.paper_id, '未知')}；"
                    f"第 {figure.page_number} 页；{figure.kind}；图注：{(figure.caption or '无')[:300]}"
                )
            parts.append("## 图像库命中（仅图注/元数据；视觉像素是否可用取决于 Vision Provider）\n" + "\n".join(rows))
        if self.artifacts:
            rows = []
            for artifact in self.artifacts[:4]:
                rows.append(
                    f"- [成果 {artifact.id}] {artifact.title}（{artifact.kind}，{artifact.quality_status}）"
                    f"\n  {(artifact.content or '')[:500]}"
                )
            parts.append("## 已有学术成果\n" + "\n".join(rows))
        return "\n\n".join(parts)[:7000]


def _project_for_user(db: Session, user: User, project_id: str | None) -> Project | None:
    if not project_id:
        return None
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        return None
    return project


def _project_items(db: Session, user: User, project_id: str) -> list[ProjectItem]:
    return list(
        db.execute(
            select(ProjectItem)
            .where(ProjectItem.user_id == user.id, ProjectItem.project_id == project_id)
            .order_by(ProjectItem.created_at.asc())
        ).scalars().all()
    )


def _user_papers(db: Session, user: User, ids: set[str]) -> dict[str, Paper]:
    if not ids:
        return {}
    return {
        paper.id: paper
        for paper in db.execute(
            select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))
        ).scalars().all()
    }


def search_knowledge(
    db: Session,
    user: User,
    query: str,
    *,
    project_id: str | None = None,
    limit: int = 6,
) -> list[tuple[KnowledgeItem, float]]:
    statement = select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)
    if project_id:
        statement = statement.where(KnowledgeItem.project_id == project_id)
    items = list(db.execute(statement.order_by(KnowledgeItem.updated_at.desc()).limit(500)).scalars().all())
    if not items:
        return []
    if not query.strip():
        return [(item, 0.0) for item in items[:limit]]
    return [(item, score) for item, score in hybrid_search(items, query, limit=limit) if score > 0.02]


def search_images(
    db: Session,
    user: User,
    query: str,
    *,
    paper_ids: list[str] | None = None,
    limit: int = 6,
) -> list[Figure]:
    statement = select(Figure).where(Figure.user_id == user.id)
    if paper_ids:
        statement = statement.where(Figure.paper_id.in_(paper_ids))
    figures = list(db.execute(statement.limit(300)).scalars().all())
    if any(figure.detected_kind == "unclassified" for figure in figures):
        from .figure_classification import classify_user_figures
        classify_user_figures(db, user)
        figures = list(db.execute(statement.limit(300)).scalars().all())
    figures = [
        figure for figure in figures
        if not figure.ignored and not figure.is_page_snapshot
    ]
    lowered = query.lower().strip()
    if not lowered:
        return figures[:limit]
    terms = [term for term in re_split(lowered) if len(term) >= 2]
    scored: list[tuple[Figure, int]] = []
    for figure in figures:
        haystack = ((figure.caption or "") + " " + (figure.note or "") + " " + (figure.table_markdown or "")).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((figure, score))
    scored.sort(key=lambda row: row[1], reverse=True)
    return [figure for figure, _ in scored[:limit]] if scored else []


def re_split(text: str) -> list[str]:
    return [part for part in re.split(r"[\s，。！？；：、,.!?;:()\[\]{}<>/|\\-]+", text) if part]


def search_artifacts(
    db: Session,
    user: User,
    query: str = "",
    *,
    project_id: str | None = None,
    limit: int = 6,
) -> list[AcademicArtifact]:
    statement = select(AcademicArtifact).where(AcademicArtifact.user_id == user.id)
    artifacts = list(db.execute(statement.order_by(AcademicArtifact.updated_at.desc()).limit(120)).scalars().all())
    if project_id:
        project_item_ids = {
            item.ref_id
            for item in db.execute(
                select(ProjectItem).where(
                    ProjectItem.user_id == user.id,
                    ProjectItem.project_id == project_id,
                    ProjectItem.kind.in_(("artifact", "成果")),
                )
            ).scalars().all()
            if item.ref_id
        }
        artifacts = [
            artifact
            for artifact in artifacts
            if artifact.id in project_item_ids or project_id in (artifact.scope_ids or [])
        ]
    lowered = query.lower().strip()
    if lowered:
        terms = [term for term in re_split(lowered) if len(term) >= 2]
        artifacts = [
            artifact
            for artifact in artifacts
            if any(term in ((artifact.title or "") + " " + (artifact.content or "")).lower() for term in terms)
        ]
    return artifacts[:limit]


def resolve_research_context(
    db: Session,
    user: User,
    question: str,
    *,
    project_id: str | None = None,
    scope_type: str = "all",
    scope_ids: list[str] | None = None,
    knowledge_ids: list[str] | None = None,
    image_ids: list[str] | None = None,
    artifact_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
    auto_retrieval: bool = True,
) -> UnifiedResearchContext:
    """Resolve explicit and question-relevant resources under one user boundary."""
    project = _project_for_user(db, user, project_id)
    if project is None and scope_type == "project" and scope_ids:
        project = _project_for_user(db, user, scope_ids[0])

    excluded = set(exclude_ids or [])
    if project is not None and project.id in excluded:
        project = None
    items = _project_items(db, user, project.id) if project else []
    notes = [item for item in items if item.kind in {"note", "笔记"} and item.id not in excluded]

    # Explicit IDs are fetched from the user's rows only; missing/foreign IDs are silently excluded.
    explicit_knowledge: list[KnowledgeItem] = []
    if knowledge_ids:
        wanted = [item for item in knowledge_ids if item not in excluded]
        if wanted:
            explicit_knowledge = list(
                db.execute(
                    select(KnowledgeItem).where(
                        KnowledgeItem.user_id == user.id, KnowledgeItem.id.in_(wanted)
                    )
                ).scalars().all()
            )

    project_knowledge_ids = {
        item.ref_id
        for item in items
        if item.kind in {"knowledge", "note_ref", "知识"} and item.ref_id and item.ref_id not in excluded
    }
    knowledge: list[KnowledgeItem] = []
    scores: dict[str, float] = {}
    seen_knowledge: set[str] = set()
    for item in explicit_knowledge:
        knowledge.append(item)
        scores[item.id] = 1.0
        seen_knowledge.add(item.id)
    if auto_retrieval:
        knowledge_hits = search_knowledge(db, user, question, project_id=project.id if project else None, limit=6)
    else:
        knowledge_hits = []
    for item, score in knowledge_hits:
        if item.id in excluded or item.id in seen_knowledge:
            continue
        if project and item.id not in project_knowledge_ids and score < 0.08:
            continue
        if not project and score < 0.08:
            continue
        knowledge.append(item)
        scores[item.id] = score
        seen_knowledge.add(item.id)
        if len(knowledge) >= 6:
            break
    if project:
        for item in db.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.user_id == user.id,
                KnowledgeItem.id.in_(project_knowledge_ids) if project_knowledge_ids else KnowledgeItem.id == "",
            )
        ).scalars().all():
            if item.id not in seen_knowledge and item.id not in excluded:
                knowledge.append(item)
                scores[item.id] = 1.0
                seen_knowledge.add(item.id)

    paper_ids = {item.ref_id for item in items if item.kind == "paper" and item.ref_id}
    paper_ids.update(item.source_paper_id for item in knowledge if item.source_paper_id)
    paper_titles = {
        paper.id: paper.title
        for paper in _user_papers(db, user, {str(value) for value in paper_ids if value}).values()
    }

    image_ids_set = {item.ref_id for item in items if item.kind in {"image", "figure", "图片"} and item.ref_id}
    explicit_image_ids = [item for item in (image_ids or []) if item not in excluded]
    images: list[Figure] = []
    seen_images: set[str] = set()
    if explicit_image_ids:
        for figure in db.execute(
            select(Figure).where(Figure.user_id == user.id, Figure.id.in_(explicit_image_ids))
        ).scalars().all():
            images.append(figure)
            seen_images.add(figure.id)
    if project and image_ids_set:
        for figure in db.execute(
            select(Figure).where(
                Figure.user_id == user.id,
                Figure.id.in_(list(image_ids_set)),
            )
        ).scalars().all():
            if figure.id not in seen_images and figure.id not in excluded:
                images.append(figure)
                seen_images.add(figure.id)
    if auto_retrieval and (any(word in question.lower() for word in IMAGE_WORDS) or explicit_image_ids):
        image_matches = search_images(db, user, question, limit=5)
        if not image_matches:
            image_matches = search_images(db, user, "", limit=5)
        for figure in image_matches:
            if figure.id not in seen_images and figure.id not in excluded:
                images.append(figure)
                seen_images.add(figure.id)
    images = images[:6]

    artifacts: list[AcademicArtifact] = []
    seen_artifacts: set[str] = set()
    artifact_item_ids = {item.ref_id for item in items if item.kind in {"artifact", "成果"} and item.ref_id}
    explicit_artifact_ids = [item for item in (artifact_ids or []) if item not in excluded]
    if explicit_artifact_ids:
        for artifact in db.execute(
            select(AcademicArtifact).where(
                AcademicArtifact.user_id == user.id,
                AcademicArtifact.id.in_(explicit_artifact_ids),
            )
        ).scalars().all():
            artifacts.append(artifact)
            seen_artifacts.add(artifact.id)
    if project:
        for artifact in search_artifacts(db, user, "", project_id=project.id, limit=4):
            if artifact.id not in seen_artifacts and artifact.id not in excluded:
                artifacts.append(artifact)
                seen_artifacts.add(artifact.id)
    if auto_retrieval and (any(word in question.lower() for word in ARTIFACT_WORDS) or explicit_artifact_ids):
        matches = search_artifacts(db, user, question, limit=4)
        if not matches:
            matches = search_artifacts(db, user, "", limit=4)
        for artifact in matches:
            if artifact.id not in seen_artifacts and artifact.id not in excluded:
                artifacts.append(artifact)
                seen_artifacts.add(artifact.id)
    artifacts = artifacts[:6]

    return UnifiedResearchContext(
        user=user,
        question=question,
        project=project,
        project_items=items,
        project_notes=notes,
        knowledge=knowledge,
        knowledge_scores=scores,
        images=images,
        artifacts=artifacts,
        paper_titles=paper_titles,
        excluded_ids=excluded,
    )


def knowledge_citation(item: KnowledgeItem, score: float = 0.0, paper_title: str | None = None) -> dict:
    return {
        "chunk_id": f"knowledge:{item.id}",
        "paper_id": item.source_paper_id,
        "paper_title": f"知识 · {item.title}",
        "page": item.source_page or 0,
        "section": f"个人知识库 · {item.kind}",
        "quote": (item.content or item.title)[:1600],
        "score": round(score, 4),
        "resource_type": "knowledge",
        "resource_id": item.id,
        "resource_title": item.title,
        "tags": list(item.tags or []),
        "source_paper_title": paper_title,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def image_citation(figure: Figure, paper_title: str | None = None) -> dict:
    return {
        "chunk_id": f"image:{figure.id}",
        "paper_id": figure.paper_id,
        "paper_title": f"图片 · {paper_title or '论文图表'} · 第 {figure.page_number} 页",
        "page": figure.page_number,
        "section": f"图像库 · {figure.kind}",
        "quote": (figure.caption or figure.note or figure.table_markdown or "图片无图注")[:1600],
        "resource_type": "image",
        "resource_id": figure.id,
        "resource_title": figure.caption or f"{figure.kind} p.{figure.page_number}",
        "image_path": figure.image_path,
        "figure_kind": figure.kind,
        "is_page_snapshot": figure.is_page_snapshot,
        "quality_score": figure.quality_score,
        "caption_confidence": figure.caption_confidence,
        "source_paper_title": paper_title,
    }


def artifact_citation(artifact: AcademicArtifact) -> dict:
    return {
        "chunk_id": f"artifact:{artifact.id}",
        "paper_id": None,
        "paper_title": f"成果 · {artifact.title}",
        "page": 0,
        "section": f"学术成果 · {artifact.kind}",
        "quote": (artifact.content or artifact.scope_statement or "")[:1600],
        "resource_type": "artifact",
        "resource_id": artifact.id,
        "resource_title": artifact.title,
        "quality_status": artifact.quality_status,
        "quality_score": artifact.quality_score,
    }


def project_citation(project: Project) -> dict:
    return {
        "chunk_id": f"project:{project.id}",
        "paper_id": None,
        "paper_title": f"项目 · {project.name}",
        "page": 0,
        "section": "研究项目",
        "quote": ((project.goal or "") + "\n" + (project.description or "")).strip()[:1600],
        "resource_type": "project",
        "resource_id": project.id,
        "resource_title": project.name,
        "progress": project.progress,
        "status": project.status,
    }


def image_asset(figure: Figure) -> tuple[bytes, str] | None:
    """Read the real image file through the storage sandbox."""
    if not figure.image_path:
        return None
    try:
        path: Path = storage.abs_path(figure.image_path)
    except ValueError:
        return None
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        suffix, "application/octet-stream"
    )
    return path.read_bytes(), media


def image_metadata(figure: Figure) -> dict:
    asset = image_asset(figure)
    if asset is None:
        return {"available": False, "reason": "图片文件不存在或路径无效"}
    data, media = asset
    width = int(figure.width or 0)
    height = int(figure.height or 0)
    try:
        from PIL import Image
        from io import BytesIO

        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            mode = image.mode
    except Exception:  # noqa: BLE001
        mode = "unknown"
    import hashlib

    return {
        "available": True,
        "media_type": media,
        "size_bytes": len(data),
        "width": width,
        "height": height,
        "mode": mode,
        "sha256": hashlib.sha256(data).hexdigest(),
        "vision_read": False,
    }


def vision_status(config) -> dict:
    """The current DeepSeek client is text-only. Keep the missing capability explicit."""
    return {
        "available": False,
        "provider": "none",
        "model": config.model if config else None,
        "reason": "当前模型客户端未配置视觉输入；只读取真实图片文件元数据，不宣称已理解像素。",
    }