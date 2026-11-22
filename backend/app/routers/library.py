"""Collections, knowledge base, projects and the knowledge graph."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Annotation,
    KnowledgeMeta,
    KnowledgeVersion,
    PaperFacet,
    Chunk,
    Collection,
    CollectionPaper,
    Conversation,
    Figure,
    KnowledgeItem,
    KnowledgeLink,
    Paper,
    Project,
    ProjectItem,
    User,
    utcnow,
)
from ..schemas import (
    CollectionCreate,
    KnowledgeMergeRequest,
    KnowledgeRollbackRequest,
    CollectionUpdate,
    KnowledgeCreate,
    KnowledgeUpdate,
    LinkCreate,
    ProjectCreate,
    ProjectItemCreate,
    ProjectUpdate,
)
from ..services.evidence import EvidenceError, create_evidence
from ..services import knowledge as knowledge_service
from ..serializers import (
    collection_out,
    knowledge_version_out,
    knowledge_out,
    link_out,
    project_item_out,
    project_out,
)

router = APIRouter(tags=["library"])


# ------------------------------------------------------------------ collections
@router.get("/collections")
def list_collections(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collections = list(db.execute(select(Collection).where(Collection.user_id == user.id).order_by(Collection.created_at.desc())).scalars().all())
    counts = dict(
        db.execute(
            select(CollectionPaper.collection_id, func.count(CollectionPaper.id))
            .join(Collection, Collection.id == CollectionPaper.collection_id)
            .where(Collection.user_id == user.id)
            .group_by(CollectionPaper.collection_id)
        ).all()
    )
    return {"items": [collection_out(c, counts.get(c.id, 0)) for c in collections]}


@router.post("/collections", status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collection = Collection(
        user_id=user.id, name=payload.name.strip()[:200], description=payload.description,
        color=payload.color or "#2F6F62",
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return {"collection": collection_out(collection)}


@router.patch("/collections/{collection_id}")
def update_collection(collection_id: str, payload: CollectionUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collection = db.get(Collection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合集不存在或无权访问")
    if payload.name is not None:
        collection.name = payload.name.strip()[:200] or collection.name
    if payload.description is not None:
        collection.description = payload.description
    if payload.color is not None:
        collection.color = payload.color
    db.commit()
    return {"collection": collection_out(collection)}


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collection = db.get(Collection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合集不存在或无权访问")
    db.delete(collection)
    db.commit()
    return {"ok": True}


@router.post("/collections/{collection_id}/papers")
def add_papers(collection_id: str, paper_ids: list[str], user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collection = db.get(Collection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合集不存在或无权访问")
    added = 0
    for paper_id in paper_ids:
        paper = db.get(Paper, paper_id)
        if paper is None or paper.user_id != user.id:
            continue
        exists = db.execute(
            select(CollectionPaper).where(CollectionPaper.collection_id == collection.id, CollectionPaper.paper_id == paper.id)
        ).scalar_one_or_none()
        if not exists:
            db.add(CollectionPaper(collection_id=collection.id, paper_id=paper.id))
            added += 1
    db.commit()
    return {"ok": True, "added": added}


@router.delete("/collections/{collection_id}/papers/{paper_id}")
def remove_paper(collection_id: str, paper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    collection = db.get(Collection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合集不存在或无权访问")
    link = db.execute(
        select(CollectionPaper).where(CollectionPaper.collection_id == collection.id, CollectionPaper.paper_id == paper_id)
    ).scalar_one_or_none()
    if link:
        db.delete(link)
        db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ knowledge
@router.get("/knowledge")
def list_knowledge(
    query: str = "",
    kind: str | None = None,
    project_id: str | None = None,
    paper_id: str | None = None,
    tag: str | None = None,
    cluster: str | None = None,
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)
    if kind:
        statement = statement.where(KnowledgeItem.kind == kind)
    if project_id:
        statement = statement.where(KnowledgeItem.project_id == project_id)
    if paper_id:
        statement = statement.where(KnowledgeItem.source_paper_id == paper_id)
    items = list(db.execute(statement.order_by(KnowledgeItem.pinned.desc(), KnowledgeItem.updated_at.desc())).scalars().all())
    if tag:
        items = [item for item in items if tag in (item.tags or [])]
    metas = {item.id: knowledge_service.ensure_meta(db, item) for item in items}
    if cluster:
        items = [item for item in items if metas.get(item.id) and metas[item.id].cluster_key == cluster]
    scores: dict[str, float] = {}
    if query.strip():
        hits = knowledge_service.hybrid_search(items, query.strip(), limit=limit)
        items = [item for item, _score in hits]
        scores = {item.id: score for item, score in hits}
    else:
        items = sorted(items, key=lambda item: (item.pinned, item.updated_at), reverse=True)[:limit]
    db.commit()
    titles = {p.id: p.title for p in db.execute(select(Paper).where(Paper.user_id == user.id)).scalars().all()}
    return {
        "items": [
            knowledge_out(item, titles.get(item.source_paper_id), metas.get(item.id), scores.get(item.id))
            for item in items
        ],
        "search": {"mode": "hybrid" if query.strip() else "list", "query": query.strip()},
    }


@router.post("/knowledge", status_code=status.HTTP_201_CREATED)
def create_knowledge(payload: KnowledgeCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.source_paper_id:
        paper = db.get(Paper, payload.source_paper_id)
        if paper is None or paper.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "来源论文不存在")
    try:
        item, meta, duplicate = knowledge_service.create_knowledge_item(
            db,
            user,
            title=payload.title,
            content=payload.content,
            kind=payload.kind,
            tags=payload.tags,
            project_id=payload.project_id,
            source_paper_id=payload.source_paper_id,
            source_page=payload.source_page,
            source_quote=payload.source_quote,
            source_chunk_id=payload.source_chunk_id,
            force=payload.force,
        )
    except knowledge_service.DuplicateKnowledge as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_knowledge",
                "message": f"发现相似知识（相似度 {exc.score:.0%}），未创建新条目。",
                "score": round(exc.score, 4),
                "candidate": knowledge_out(exc.candidate),
            },
        ) from exc
    if item.source_quote and item.source_paper_id:
        try:
            create_evidence(
                db,
                user,
                paper_id=item.source_paper_id,
                chunk_id=item.source_chunk_id,
                page=item.source_page,
                quote=item.source_quote,
                claim=item.title,
                evidence_type="direct",
                source_type="knowledge",
                source_id=item.id,
            )
        except EvidenceError:
            pass
    db.commit()
    db.refresh(item)
    return {"item": knowledge_out(item, meta=meta), "duplicate_of": duplicate.id if duplicate else None}


@router.patch("/knowledge/{item_id}")
def update_knowledge(item_id: str, payload: KnowledgeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    meta, changed = knowledge_service.update_knowledge_item(db, item, payload)
    duplicate, score = knowledge_service.find_duplicate(db, user, item.title, item.content, exclude_id=item.id)
    warnings = []
    if duplicate is not None and score >= knowledge_service.DUPLICATE_THRESHOLD:
        warnings.append(f"与「{duplicate.title}」相似度 {score:.0%}，可考虑合并。")
    db.commit()
    return {
        "item": knowledge_out(item, meta=meta),
        "changed_fields": changed,
        "warnings": warnings,
    }


@router.delete("/knowledge/{item_id}")
def delete_knowledge(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    db.delete(item)
    db.commit()
    return {"ok": True}




@router.get("/knowledge/duplicates")
def knowledge_duplicates(
    threshold: float = Query(0.82, ge=0.5, le=0.99),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": knowledge_service.duplicate_pairs(db, user, threshold=threshold), "threshold": threshold}


@router.get("/knowledge/clusters")
def knowledge_clusters(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    items = knowledge_service.clusters(db, user)
    return {"items": items, "total": sum(item["count"] for item in items)}




@router.post("/knowledge/{item_id}/merge")
def merge_knowledge(
    item_id: str,
    payload: KnowledgeMergeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(KnowledgeItem, item_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    sources = list(
        db.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.user_id == user.id,
                KnowledgeItem.id.in_(payload.source_ids),
                KnowledgeItem.id != target.id,
            )
        ).scalars().all()
    )
    if not sources:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "没有可合并的条目")
    appended = False
    tags = list(target.tags or [])
    for source in sources:
        if source.content and source.content not in (target.content or ""):
            target.content = (target.content or "") + "\n\n---\n" + source.content
            appended = True
        for tag in (source.tags or []):
            if tag not in tags:
                tags.append(tag)
        db.delete(source)
    target.tags = tags[:12]
    target.updated_at = utcnow()
    meta = knowledge_service.ensure_meta(db, target)
    meta.version += 1
    meta.auto_tags = knowledge_service.extract_auto_tags(db, target)
    meta.cluster_key, meta.cluster_label = knowledge_service.cluster_for(meta.auto_tags, target.kind)
    knowledge_service.snapshot(db, target, meta, payload.note or "合并相似条目", ["content", "tags"] if appended else ["tags"])
    db.commit()
    db.refresh(target)
    db.refresh(meta)
    return {"item": knowledge_out(target, meta=meta), "merged": len(sources)}


@router.get("/knowledge/{item_id}/versions")
def list_knowledge_versions(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(KnowledgeItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    meta = knowledge_service.ensure_meta(db, item)
    db.commit()
    versions = list(
        db.execute(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.item_id == item.id)
            .order_by(KnowledgeVersion.version.desc())
        ).scalars().all()
    )
    return {"item": knowledge_out(item, meta=meta), "versions": [knowledge_version_out(v) for v in versions]}


@router.post("/knowledge/{item_id}/versions/{version}/rollback")
def rollback_knowledge_version(
    item_id: str,
    version: int,
    payload: KnowledgeRollbackRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(KnowledgeItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    try:
        _target, meta = knowledge_service.rollback_knowledge(db, item, version, payload.note if payload else None)
    except knowledge_service.KnowledgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"item": knowledge_out(item, meta=meta), "version": meta.version}


# ------------------------------------------------------------------ links & graph
@router.post("/knowledge/links", status_code=status.HTTP_201_CREATED)
def create_link(payload: LinkCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    link = KnowledgeLink(
        user_id=user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        relation=payload.relation,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"link": link_out(link)}


@router.delete("/knowledge/links/{link_id}")
def delete_link(link_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    link = db.get(KnowledgeLink, link_id)
    if link is None or link.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "关联不存在或无权访问")
    db.delete(link)
    db.commit()
    return {"ok": True}


def _graph_slug(text: str) -> str:
    return hashlib.sha1(text.strip().casefold().encode("utf-8")).hexdigest()[:10]


@router.get("/knowledge/graph")
def knowledge_graph(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    papers = list(db.execute(select(Paper).where(Paper.user_id == user.id)).scalars().all())
    items = list(db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)).scalars().all())
    links = list(db.execute(select(KnowledgeLink).where(KnowledgeLink.user_id == user.id)).scalars().all())
    annotations = list(
        db.execute(select(Annotation).where(Annotation.user_id == user.id, Annotation.deleted_at.is_(None))).scalars().all()
    )
    facets = list(db.execute(select(PaperFacet).where(PaperFacet.user_id == user.id)).scalars().all())
    nodes = []
    node_ids: set[str] = set()
    edges = []
    edge_ids: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str, meta: dict) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({"id": node_id, "type": node_type, "label": label[:90], "meta": meta})

    def add_edge(edge_id: str, source: str, target: str, relation: str) -> None:
        if edge_id in edge_ids or source not in node_ids or target not in node_ids:
            return
        edge_ids.add(edge_id)
        edges.append({"id": edge_id, "source": source, "target": target, "relation": relation})

    for paper in papers:
        add_node(
            f"paper:{paper.id}", "paper", paper.title[:70],
            {"year": paper.year, "pages": paper.page_count, "paper_id": paper.id, "annotations": sum(1 for a in annotations if a.paper_id == paper.id)},
        )
    metas = {
        meta.item_id: meta
        for meta in db.execute(select(KnowledgeMeta).where(KnowledgeMeta.user_id == user.id)).scalars().all()
    }
    for item in items:
        meta = metas.get(item.id)
        auto_tags = meta.auto_tags if meta is not None else knowledge_service.extract_auto_tags(db, item)
        add_node(
            f"knowledge:{item.id}", "knowledge", item.title[:70],
            {"kind": item.kind, "paper_id": item.source_paper_id, "knowledge_id": item.id, "auto_tags": auto_tags},
        )
        for tag in (auto_tags or [])[:6]:
            tag_id = f"tag:{_graph_slug(tag)}"
            add_node(tag_id, "tag", tag, {"tag": tag})
            add_edge(f"tag-{item.id}-{_graph_slug(tag)}", f"knowledge:{item.id}", tag_id, "tagged")
        if item.source_paper_id:
            add_edge(f"src-{item.id}", f"knowledge:{item.id}", f"paper:{item.source_paper_id}", "derived_from")

    field_map = (("method", "method", "uses_method"), ("dataset", "dataset", "uses_dataset"), ("research_question", "question", "studies"))
    for facet in facets:
        paper = next((p for p in papers if p.id == facet.paper_id), None)
        if paper is None:
            continue
        for field, node_type, relation in field_map:
            value = ((facet.fields or {}).get(field) or {}).get("text") or ""
            if not value or value == "未提及":
                continue
            concept_id = f"{node_type}:{_graph_slug(value)}"
            add_node(concept_id, node_type, value[:70], {"field": field})
            add_edge(f"concept-{paper.id}-{concept_id}", f"paper:{paper.id}", concept_id, relation)

    for link in links:
        add_edge(link.id, f"{link.source_type}:{link.source_id}", f"{link.target_type}:{link.target_id}", link.relation)
    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------------ projects
@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    projects = list(db.execute(select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())).scalars().all())
    counts: dict[str, dict[str, int]] = {}
    for project in projects:
        rows = db.execute(
            select(ProjectItem.kind, func.count(ProjectItem.id)).where(ProjectItem.project_id == project.id).group_by(ProjectItem.kind)
        ).all()
        counts[project.id] = {kind: count for kind, count in rows}
    return {"items": [project_out(p, counts.get(p.id, {})) for p in projects]}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = Project(
        user_id=user.id, name=payload.name.strip()[:240], description=payload.description,
        goal=payload.goal, color=payload.color or "#2F6F62",
    )
    db.add(project)
    db.flush()
    paper_ids = list(dict.fromkeys(paper_id for paper_id in payload.paper_ids if paper_id))
    if paper_ids:
        papers = list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(paper_ids))).scalars().all())
        by_id = {paper.id: paper for paper in papers}
        for paper_id in paper_ids:
            paper = by_id.get(paper_id)
            if paper is None:
                continue
            db.add(ProjectItem(
                project_id=project.id, user_id=user.id, kind="paper",
                ref_id=paper.id, title=paper.title[:390],
                meta={"year": paper.year},
            ))
    db.commit()
    db.refresh(project)
    counts = {}
    if paper_ids:
        counts["paper"] = len({paper.id for paper in papers})
    return {"project": project_out(project, counts)}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
    items = list(db.execute(select(ProjectItem).where(ProjectItem.project_id == project.id).order_by(ProjectItem.created_at.desc())).scalars().all())
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return {"project": project_out(project, counts), "items": [project_item_out(i) for i in items]}


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
    for field_name in ("name", "description", "goal", "status", "progress", "color"):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(project, field_name, value)
    if payload.progress is not None:
        project.progress = max(0, min(100, payload.progress))
    project.updated_at = utcnow()
    db.commit()
    return {"project": project_out(project)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/items", status_code=status.HTTP_201_CREATED)
def add_project_item(project_id: str, payload: ProjectItemCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
    item = ProjectItem(
        project_id=project.id,
        user_id=user.id,
        kind=payload.kind,
        ref_id=payload.ref_id,
        title=payload.title[:390],
        content=payload.content,
        meta=payload.meta,
    )
    db.add(item)
    project.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    return {"item": project_item_out(item)}


@router.delete("/projects/{project_id}/items/{item_id}")
def delete_project_item(project_id: str, item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(ProjectItem, item_id)
    if item is None or item.user_id != user.id or item.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目条目不存在或无权访问")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ stats
@router.get("/library/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    def count(model, *conditions):
        return db.execute(select(func.count()).select_from(model).where(*conditions)).scalar() or 0

    papers_total = count(Paper, Paper.user_id == user.id)
    papers_ready = count(Paper, Paper.user_id == user.id, Paper.status == "ready")
    pages = db.execute(select(func.sum(Paper.page_count)).where(Paper.user_id == user.id)).scalar() or 0
    chunks = db.execute(
        select(func.count(Chunk.id)).join(Paper, Paper.id == Chunk.paper_id).where(Paper.user_id == user.id)
    ).scalar() or 0
    annotations = count(Annotation, Annotation.user_id == user.id, Annotation.deleted_at.is_(None))
    knowledge = count(KnowledgeItem, KnowledgeItem.user_id == user.id)
    figures = count(Figure, Figure.user_id == user.id)
    projects = count(Project, Project.user_id == user.id)
    conversations = count(Conversation, Conversation.user_id == user.id)
    return {
        "papers": papers_total,
        "papers_ready": papers_ready,
        "pages": int(pages),
        "chunks": int(chunks),
        "annotations": annotations,
        "knowledge": knowledge,
        "figures": figures,
        "projects": projects,
        "conversations": conversations,
    }