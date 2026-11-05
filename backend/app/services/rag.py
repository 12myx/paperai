"""Corpus loading and citation-aware retrieval over a user's papers."""
from __future__ import annotations

import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Paper
from .retrieval import Document, HybridIndex

_CACHE: dict[str, tuple[float, HybridIndex, dict[str, Chunk], dict[str, Paper]]] = {}
_DOC_CACHE: dict[tuple[str, str], tuple[str, list[Document], list[Chunk]]] = {}
_TTL_SECONDS = 90
_VERSION: dict[str, int] = {}
_STATS = Counter()


def invalidate(user_id: str) -> None:
    _VERSION[user_id] = _VERSION.get(user_id, 0) + 1
    for key in [k for k in _CACHE if k.startswith(f"{user_id}:")]:
        _CACHE.pop(key, None)
    for key in [k for k in _DOC_CACHE if k[0] == user_id]:
        _DOC_CACHE.pop(key, None)


def invalidate_paper(user_id: str, paper_id: str) -> None:
    """Keep other papers' cached documents; only drop the changed paper."""
    _VERSION[user_id] = _VERSION.get(user_id, 0) + 1
    for key in [k for k in _CACHE if k.startswith(f"{user_id}:")]:
        _CACHE.pop(key, None)
    _DOC_CACHE.pop((user_id, paper_id), None)


def cache_stats() -> dict:
    return {
        "index_entries": len(_CACHE),
        "document_entries": len(_DOC_CACHE),
        "index_builds": _STATS["index_builds"],
        "document_hits": _STATS["document_hits"],
        "document_misses": _STATS["document_misses"],
        "last_build_ms": _STATS["last_build_ms"],
    }


def get_index(db: Session, user_id: str, paper_ids: list[str] | None = None):
    ids = sorted(paper_ids) if paper_ids else None
    version = _VERSION.get(user_id, 0)
    key = f"{user_id}:{version}:{','.join(ids) if ids else 'all'}"
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < _TTL_SECONDS:
        return cached[1], cached[2], cached[3]

    started = time.time()
    paper_query = select(Paper).where(Paper.user_id == user_id, Paper.status == "ready")
    if paper_ids:
        paper_query = paper_query.where(Paper.id.in_(paper_ids))
    papers = list(db.execute(paper_query).scalars().all())

    documents: list[Document] = []
    chunk_map: dict[str, Chunk] = {}
    paper_map: dict[str, Paper] = {}
    for paper in papers:
        signature = f"{paper.updated_at}:{paper.title}:{(paper.meta or {}).get('chunk_count', '')}"
        cached = _DOC_CACHE.get((user_id, paper.id))
        if cached and cached[0] == signature:
            docs, chunks = cached[1], cached[2]
            _STATS["document_hits"] += 1
        else:
            chunks = list(
                db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
            )
            docs = [
                Document(
                    chunk_id=chunk.id,
                    paper_id=paper.id,
                    paper_title=paper.title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section_title,
                    text=chunk.text,
                    tags=list(chunk.tags or []),
                )
                for chunk in chunks
            ]
            _DOC_CACHE[(user_id, paper.id)] = (signature, docs, chunks)
            _STATS["document_misses"] += 1
        paper_map[paper.id] = paper
        for chunk in chunks:
            chunk_map[chunk.id] = chunk
        documents.extend(docs)

    index = HybridIndex(documents)
    _STATS["index_builds"] += 1
    _STATS["last_build_ms"] = int((time.time() - started) * 1000)
    _CACHE[key] = (time.time(), index, chunk_map, paper_map)
    if len(_CACHE) > 24:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    return index, chunk_map, paper_map


def search(
    db: Session,
    user_id: str,
    query: str,
    paper_ids: list[str] | None = None,
    top_k: int = 8,
) -> list[dict]:
    index, chunk_map, paper_map = get_index(db, user_id, paper_ids)
    hits = index.search(query, top_k=top_k)
    citations: list[dict] = []
    for position, (document, score) in enumerate(hits, start=1):
        chunk = chunk_map.get(document.chunk_id)
        paper = paper_map.get(document.paper_id)
        if chunk is None or paper is None:
            continue
        quote = chunk.text.strip()
        if len(quote) > 1400:
            quote = quote[:1390].rsplit(" ", 1)[0] + " …"
        citations.append(
            {
                "key": f"C{position}",
                "chunk_id": chunk.id,
                "paper_id": paper.id,
                "paper_title": paper.title,
                "paper_year": paper.year,
                "section": chunk.section_title,
                "page": chunk.page_start,
                "page_end": chunk.page_end,
                "quote": quote,
                "score": round(float(score), 4),
                "kind": chunk.kind,
                "tags": list(chunk.tags or []),
            }
        )
    return citations


def format_citations(citations: list[dict]) -> str:
    if not citations:
        return "（没有检索到证据片段）"
    blocks = []
    for citation in citations:
        source = f"{citation['paper_title']}"
        if citation.get("paper_year"):
            source += f", {citation['paper_year']}"
        blocks.append(
            f"[{citation['key']}] {source} · 第 {citation['page']} 页 · {citation['section']}\n"
            f"{citation['quote']}"
        )
    return "\n\n".join(blocks)