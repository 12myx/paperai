"""P7 knowledge intelligence: auto tags, hybrid search, duplicates, versions.

The lexical hybrid index is shared with paper retrieval (BM25 + character
trigram cosine), so it works offline for mixed Chinese/English notes. No neural
embedding is claimed when none is configured.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Chunk, KnowledgeItem, KnowledgeMeta, KnowledgeVersion, Paper, User, utcnow
from .retrieval import Document, HybridIndex, STOPWORDS, _ngram_vector, tokenize

DUPLICATE_THRESHOLD = 0.82

KIND_LABELS = {
    "note": "笔记", "summary": "总结", "insight": "洞见", "method": "方法",
    "result": "结果", "question": "问题", "quote": "引用",
}
TAG_LABELS = {
    "abstract": "摘要", "introduction": "背景", "method": "方法", "experiment": "实验",
    "result": "结果", "conclusion": "结论", "limitation": "局限", "future-work": "未来工作",
    "discussion": "讨论", "body": "正文", "heading": "章节",
}
IGNORED_TERMS = {
    "paperlens", "paper", "papers", "method", "methods", "using", "used", "based",
    "approach", "result", "results", "knowledge", "note", "unique", "debug", "test",
}
KNOWN_CJK = (
    "检索", "对比学习", "证据", "引用", "方法", "实验", "结论", "局限", "数据集",
    "研究问题", "预训练", "微调", "评估", "基线", "多模态", "可复现",
)


class DuplicateKnowledge(Exception):
    def __init__(self, candidate: KnowledgeItem, score: float) -> None:
        self.candidate = candidate
        self.score = score
        super().__init__("duplicate knowledge")


class KnowledgeError(ValueError):
    pass


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _slug(text: str) -> str:
    return hashlib.sha1(_normalize(text).encode("utf-8")).hexdigest()[:12]


def _source_chunk(db: Session, item: KnowledgeItem) -> Chunk | None:
    if not item.source_chunk_id:
        return None
    return db.get(Chunk, item.source_chunk_id)


def extract_auto_tags(db: Session, item: KnowledgeItem) -> list[str]:
    tags: list[str] = []
    kind_label = KIND_LABELS.get(item.kind)
    if kind_label:
        tags.append(kind_label)
    chunk = _source_chunk(db, item)
    if chunk is not None:
        for raw in (chunk.tags or []):
            label = TAG_LABELS.get(raw)
            if label and label not in tags:
                tags.append(label)
        if chunk.section_title:
            section = chunk.section_title[:24]
            if len(section) >= 2 and section not in tags:
                tags.append(section)
    text = (item.title or "") + "\n" + (item.content or "")
    counts: Counter = Counter()
    for term in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", text.lower()):
        if term in STOPWORDS or term in IGNORED_TERMS or term.isdigit():
            continue
        counts[term] += 2 if term in (item.title or "").lower() else 1
    for term, _count in counts.most_common(8):
        if len(tags) >= 7:
            break
        if term not in tags:
            tags.append(term)
    for term in KNOWN_CJK:
        if term in text and term not in tags and len(tags) < 8:
            tags.append(term)
    return tags[:8]


def cluster_for(tags: list[str], kind: str) -> tuple[str, str]:
    for label in ("方法", "数据集", "研究问题", "局限", "实验", "结论"):
        if label in tags:
            return _slug(label), label
    generic = set(KIND_LABELS.values()) | set(TAG_LABELS.values()) | {"笔记", "洞见", "正文", "章节", "论文", "知识", "测试"}
    for tag in tags:
        if tag not in generic and len(tag) >= 2:
            return _slug(tag), tag
    label = KIND_LABELS.get(kind, "笔记")
    return _slug(label), label


def ensure_meta(db: Session, item: KnowledgeItem, *, create_version: bool = True) -> KnowledgeMeta:
    meta = db.execute(select(KnowledgeMeta).where(KnowledgeMeta.item_id == item.id)).scalar_one_or_none()
    if meta is None:
        auto_tags = extract_auto_tags(db, item)
        key, label = cluster_for(auto_tags, item.kind)
        try:
            with db.begin_nested():
                meta = KnowledgeMeta(
                    user_id=item.user_id,
                    item_id=item.id,
                    auto_tags=auto_tags,
                    cluster_key=key,
                    cluster_label=label,
                    version=1,
                )
                db.add(meta)
                db.flush()
                if create_version:
                    db.add(
                        KnowledgeVersion(
                            user_id=item.user_id,
                            item_id=item.id,
                            version=1,
                            title=item.title,
                            content=item.content,
                            kind=item.kind,
                            tags=item.tags or [],
                            note="创建",
                            changed_fields=["title", "content", "kind", "tags"],
                        )
                    )
                    db.flush()
            return meta
        except IntegrityError:
            meta = db.execute(select(KnowledgeMeta).where(KnowledgeMeta.item_id == item.id)).scalar_one_or_none()
            if meta is None:
                raise
            return meta
    fresh_tags = extract_auto_tags(db, item)
    if fresh_tags != (meta.auto_tags or []):
        meta.auto_tags = fresh_tags
    next_key, next_label = cluster_for(meta.auto_tags, item.kind)
    if (meta.cluster_key, meta.cluster_label) != (next_key, next_label):
        meta.cluster_key, meta.cluster_label = next_key, next_label
    if create_version:
        existing = db.execute(
            select(KnowledgeVersion).where(KnowledgeVersion.item_id == item.id, KnowledgeVersion.version == meta.version)
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                KnowledgeVersion(
                    user_id=item.user_id, item_id=item.id, version=meta.version,
                    title=item.title, content=item.content, kind=item.kind, tags=item.tags or [],
                    note="补建版本", changed_fields=[],
                )
            )
    return meta


def snapshot(db: Session, item: KnowledgeItem, meta: KnowledgeMeta, note: str, changed: list[str]) -> KnowledgeVersion:
    version = meta.version
    existing = db.execute(
        select(KnowledgeVersion).where(KnowledgeVersion.item_id == item.id, KnowledgeVersion.version == version)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = KnowledgeVersion(
        user_id=item.user_id, item_id=item.id, version=version,
        title=item.title, content=item.content, kind=item.kind, tags=item.tags or [],
        note=note, changed_fields=changed,
    )
    db.add(row)
    return row


def find_duplicate(
    db: Session,
    user: User,
    title: str,
    content: str,
    *,
    exclude_id: str | None = None,
) -> tuple[KnowledgeItem | None, float]:
    probe = _ngram_vector(_normalize(title) + " " + _normalize(content))
    if not probe.any():
        return None, 0.0
    statement = select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)
    if exclude_id:
        statement = statement.where(KnowledgeItem.id != exclude_id)
    best, best_score = None, 0.0
    for item in db.execute(statement.limit(400)).scalars().all():
        vector = _ngram_vector(_normalize(item.title) + " " + _normalize(item.content))
        score = float(np.dot(probe, vector))
        if _normalize(item.title) == _normalize(title) and _normalize(item.content) == _normalize(content):
            score = 1.0
        if score > best_score:
            best, best_score = item, score
    return best, best_score


def create_knowledge_item(
    db: Session,
    user: User,
    *,
    title: str,
    content: str,
    kind: str,
    tags: list[str],
    project_id: str | None,
    source_paper_id: str | None,
    source_page: int | None,
    source_quote: str | None,
    source_chunk_id: str | None,
    force: bool = False,
) -> tuple[KnowledgeItem, KnowledgeMeta, KnowledgeItem | None]:
    candidate, score = find_duplicate(db, user, title, content)
    if candidate is not None and score >= DUPLICATE_THRESHOLD and not force:
        raise DuplicateKnowledge(candidate, score)
    item = KnowledgeItem(
        user_id=user.id,
        title=title.strip()[:390],
        content=content,
        kind=kind,
        tags=tags[:12],
        project_id=project_id,
        source_paper_id=source_paper_id,
        source_page=source_page,
        source_quote=source_quote,
        source_chunk_id=source_chunk_id,
    )
    db.add(item)
    db.flush()
    meta = ensure_meta(db, item)
    if candidate is not None and score >= DUPLICATE_THRESHOLD:
        meta.duplicate_of = candidate.id
    db.commit()
    db.refresh(item)
    db.refresh(meta)
    return item, meta, candidate if score >= DUPLICATE_THRESHOLD else None


def update_knowledge_item(db: Session, item: KnowledgeItem, payload: Any) -> tuple[KnowledgeMeta, list[str]]:
    meta = ensure_meta(db, item)
    changed = []
    for field_name in ("title", "content", "kind", "project_id"):
        value = getattr(payload, field_name)
        if value is not None and getattr(item, field_name) != value:
            setattr(item, field_name, value)
            changed.append(field_name)
    if payload.tags is not None and (item.tags or []) != payload.tags[:12]:
        item.tags = payload.tags[:12]
        changed.append("tags")
    if payload.pinned is not None:
        item.pinned = payload.pinned
    if changed:
        meta.version += 1
        meta.auto_tags = extract_auto_tags(db, item)
        meta.cluster_key, meta.cluster_label = cluster_for(meta.auto_tags, item.kind)
        snapshot(db, item, meta, "编辑", changed)
        item.updated_at = utcnow()
        meta.updated_at = utcnow()
    db.commit()
    db.refresh(meta)
    db.refresh(item)
    return meta, changed


def rollback_knowledge(db: Session, item: KnowledgeItem, version: int, note: str | None = None) -> tuple[KnowledgeVersion, KnowledgeMeta]:
    meta = ensure_meta(db, item)
    target = db.execute(
        select(KnowledgeVersion).where(KnowledgeVersion.item_id == item.id, KnowledgeVersion.version == version)
    ).scalar_one_or_none()
    if target is None:
        raise KnowledgeError("版本不存在")
    item.title = target.title
    item.content = target.content
    item.kind = target.kind
    item.tags = target.tags or []
    item.updated_at = utcnow()
    meta.version += 1
    meta.auto_tags = extract_auto_tags(db, item)
    meta.cluster_key, meta.cluster_label = cluster_for(meta.auto_tags, item.kind)
    snapshot(db, item, meta, note or f"回滚到 v{version}", ["title", "content", "kind", "tags"])
    db.commit()
    db.refresh(meta)
    return target, meta


def hybrid_search(items: list[KnowledgeItem], query: str, limit: int = 100) -> list[tuple[KnowledgeItem, float]]:
    if not items or not query.strip():
        return [(item, 0.0) for item in items[:limit]]
    by_id = {item.id: item for item in items}
    documents = [
        Document(
            chunk_id=item.id,
            paper_id=item.source_paper_id or "",
            paper_title=item.title,
            page_start=item.source_page or 0,
            page_end=item.source_page or 0,
            section=item.kind,
            text=" ".join([item.title or "", item.content or "", " ".join(item.tags or [])]),
            tags=item.tags or [],
        )
        for item in items
    ]
    index = HybridIndex(documents)
    hits = index.search(query, top_k=min(limit, 100))
    return [(by_id[doc.chunk_id], score) for doc, score in hits if doc.chunk_id in by_id]


def duplicate_pairs(db: Session, user: User, threshold: float = DUPLICATE_THRESHOLD, limit: int = 30) -> list[dict]:
    items = list(db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)).scalars().all())
    vectors = {
        item.id: _ngram_vector(_normalize(item.title) + " " + _normalize(item.content))
        for item in items
    }
    pairs = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            score = float(np.dot(vectors[left.id], vectors[right.id]))
            if score >= threshold:
                pairs.append((score, left, right))
    pairs.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 4),
            "left": {"id": left.id, "title": left.title, "kind": left.kind},
            "right": {"id": right.id, "title": right.title, "kind": right.kind},
        }
        for score, left, right in pairs[:limit]
    ]


def clusters(db: Session, user: User) -> list[dict]:
    items = list(db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)).scalars().all())
    metas = {
        meta.item_id: meta
        for meta in db.execute(select(KnowledgeMeta).where(KnowledgeMeta.user_id == user.id)).scalars().all()
    }
    grouped: dict[str, dict] = {}
    for item in items:
        meta = metas.get(item.id)
        if meta is not None:
            key, label = cluster_for(meta.auto_tags or [], item.kind)
        else:
            tags = extract_auto_tags(db, item)
            key, label = cluster_for(tags, item.kind)
        bucket = grouped.setdefault(key, {"key": key, "label": label, "count": 0, "item_ids": []})
        bucket["count"] += 1
        bucket["item_ids"].append(item.id)
    return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)