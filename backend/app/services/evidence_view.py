"""Human-readable source context for evidence review.

Evidence records can point at a paper chunk, an AI conversation, a research
analysis, an artifact, a knowledge item, or an annotation. The evidence library
must let a reviewer jump to the generated source as well as the original text.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AcademicArtifact,
    Annotation,
    Conversation,
    Evidence,
    KnowledgeItem,
    Message,
    Paper,
    ResearchAnalysis,
    User,
)


def _clip(text: str | None, limit: int = 600) -> str:
    value = (text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def build_source_contexts(
    db: Session,
    user: User,
    rows: list[tuple[Evidence, str | None]],
) -> dict[str, dict]:
    evidence_rows = [row[0] for row in rows]
    message_ids = [row.source_id for row in evidence_rows if row.source_type == "message" and row.source_id]
    analysis_ids = [row.source_id for row in evidence_rows if row.source_type == "analysis" and row.source_id]
    artifact_ids = [row.source_id for row in evidence_rows if row.source_type in {"artifact", "artifact_summary"} and row.source_id]
    knowledge_ids = [row.source_id for row in evidence_rows if row.source_type == "knowledge" and row.source_id]
    annotation_ids = [row.source_id for row in evidence_rows if row.source_type == "annotation" and row.source_id]

    messages = {
        item.id: item
        for item in db.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user.id, Message.id.in_(message_ids))
        ).scalars().all()
    } if message_ids else {}
    conversation_ids = [item.conversation_id for item in messages.values()]
    conversations = {
        item.id: item
        for item in db.execute(
            select(Conversation).where(Conversation.user_id == user.id, Conversation.id.in_(conversation_ids))
        ).scalars().all()
    } if conversation_ids else {}
    analyses = {
        item.id: item
        for item in db.execute(select(ResearchAnalysis).where(ResearchAnalysis.user_id == user.id, ResearchAnalysis.id.in_(analysis_ids))).scalars().all()
    } if analysis_ids else {}
    artifacts = {
        item.id: item
        for item in db.execute(select(AcademicArtifact).where(AcademicArtifact.user_id == user.id, AcademicArtifact.id.in_(artifact_ids))).scalars().all()
    } if artifact_ids else {}
    knowledge = {
        item.id: item
        for item in db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id, KnowledgeItem.id.in_(knowledge_ids))).scalars().all()
    } if knowledge_ids else {}
    annotations = {
        item.id: item
        for item in db.execute(select(Annotation).where(Annotation.user_id == user.id, Annotation.id.in_(annotation_ids))).scalars().all()
    } if annotation_ids else {}
    papers = {
        item.id: item
        for item in db.execute(select(Paper).where(Paper.user_id == user.id)).scalars().all()
    }

    contexts: dict[str, dict] = {}
    for evidence in evidence_rows:
        source = None
        label = "手动记录"
        title = ""
        excerpt = ""
        url = None
        available = False
        if evidence.source_type == "message":
            message = messages.get(evidence.source_id or "")
            if message:
                conversation = conversations.get(message.conversation_id)
                source = conversation
                label = "AI 对话"
                title = conversation.title if conversation else "AI 对话"
                excerpt = message.content
                url = "/app?conversation=" + conversation.id if conversation else None
                available = True
        elif evidence.source_type == "analysis":
            analysis = analyses.get(evidence.source_id or "")
            if analysis:
                source = analysis
                label = "AI 分析"
                title = analysis.title
                excerpt = analysis.content
                if len(analysis.paper_ids or []) == 1:
                    url = "/app/papers/" + analysis.paper_ids[0]
                available = True
        elif evidence.source_type in {"artifact", "artifact_summary"}:
            artifact = artifacts.get(evidence.source_id or "")
            if artifact:
                source = artifact
                label = "学术成果"
                title = artifact.title
                excerpt = artifact.content
                url = "/app/artifacts?focus=" + artifact.id
                available = True
        elif evidence.source_type == "knowledge":
            item = knowledge.get(evidence.source_id or "")
            if item:
                source = item
                label = "知识条目"
                title = item.title
                excerpt = item.content
                url = "/app/knowledge?focus=" + item.id
                available = True
        elif evidence.source_type == "annotation":
            annotation = annotations.get(evidence.source_id or "")
            if annotation:
                source = annotation
                label = "批注"
                title = annotation.note or "论文批注"
                excerpt = annotation.quote
                url = "/app/papers/" + annotation.paper_id + "?annotation=" + annotation.id
                available = True
        elif evidence.paper_id:
            paper = papers.get(evidence.paper_id)
            if paper:
                label = "论文"
                title = paper.title
                excerpt = evidence.quote
                available = True

        gap_reason = None
        if evidence.evidence_type == "insufficient":
            if not available:
                gap_reason = "生成来源记录已不存在；无法还原当时的生成上下文。"
            elif not evidence.chunk_id or not evidence.paper_id:
                gap_reason = "该结论在生成内容中存在，但未定位到可核验的原文切片。"
            else:
                gap_reason = "未找到足够支撑该结论的原文证据。"
        elif not evidence.verified and evidence.quote:
            gap_reason = evidence.verification_note or "引用未能通过原文核验。"

        contexts[evidence.id] = {
            "source_label": label,
            "source_title": title,
            "source_excerpt": _clip(excerpt),
            "source_url": url,
            "source_available": available,
            "gap_reason": gap_reason,
            "paper_title": next((title for paper_id, title in [(evidence.paper_id, papers[evidence.paper_id].title if evidence.paper_id in papers else None)] if paper_id and title), None),
        }
    return contexts