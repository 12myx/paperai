"""Consistent JSON serialization for ORM objects."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import (
    AcademicArtifact,
    ProcessingJob,
    AgentTask,
    ArtifactQualityReport,
    Evidence,
    KnowledgeMeta,
    KnowledgeVersion,
    IntelligenceReport,
    ResearchInsight,
    AgentRun,
    AgentStep,
    Annotation,
    Collection,
    Conversation,
    ExportRecord,
    Figure,
    KnowledgeItem,
    KnowledgeLink,
    Message,
    Paper,
    Project,
    ProjectItem,
    User,
    UserSettings,
)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds") + "Z"


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "affiliation": user.affiliation,
        "avatar_color": user.avatar_color,
        "plan": user.plan,
        "created_at": iso(user.created_at),
        "last_login_at": iso(user.last_login_at),
    }


def paper_brief(paper: Paper, chunk_count: int | None = None) -> dict[str, Any]:
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "venue": paper.venue,
        "abstract": (paper.abstract or "")[:600],
        "language": paper.language,
        "filename": paper.filename,
        "size_bytes": paper.size_bytes,
        "page_count": paper.page_count,
        "status": paper.status,
        "error": paper.error,
        "tags": paper.tags or [],
        "favorite": paper.favorite,
        "note": paper.note,
        "created_at": iso(paper.created_at),
        "updated_at": iso(paper.updated_at),
        "chunk_count": chunk_count,
        "doi": (paper.meta or {}).get("doi"),
    }


def paper_detail(paper: Paper, sections: list | None = None, figures_count: int = 0, annotations_count: int = 0, chunks_count: int = 0) -> dict[str, Any]:
    data = paper_brief(paper)
    data.update(
        {
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "level": section.level,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                }
                for section in (sections or [])
            ],
            "figures_count": figures_count,
            "annotations_count": annotations_count,
            "chunks_count": chunks_count,
            "meta": paper.meta or {},
        }
    )
    return data


def annotation_out(annotation: Annotation) -> dict[str, Any]:
    return {
        "id": annotation.id,
        "paper_id": annotation.paper_id,
        "page": annotation.page_number,
        "color": annotation.color,
        "quote": annotation.quote,
        "rects": annotation.rects or [],
        "note": annotation.note,
        "tags": annotation.tags or [],
        "favorite": annotation.favorite,
        "created_at": iso(annotation.created_at),
        "updated_at": iso(annotation.updated_at),
        "deleted_at": iso(annotation.deleted_at),
    }


def figure_out(figure: Figure, paper_title: str | None = None) -> dict[str, Any]:
    return {
        "id": figure.id,
        "paper_id": figure.paper_id,
        "paper_title": paper_title,
        "page": figure.page_number,
        "kind": figure.kind,
        "caption": figure.caption,
        "width": figure.width,
        "height": figure.height,
        "ai_explanation": figure.ai_explanation,
        "note": figure.note,
        "saved": figure.saved,
        "table_markdown": figure.table_markdown,
        "image_url": f"/api/figures/{figure.id}/image" if figure.image_path else None,
        "detected_kind": figure.detected_kind,
        "quality_score": figure.quality_score,
        "caption_confidence": figure.caption_confidence,
        "is_page_snapshot": figure.is_page_snapshot,
        "ignored": figure.ignored,
        "review_status": figure.review_status,
        "visual_status": figure.visual_status,
        "needs_review": figure.detected_kind in {"unclassified", "page_snapshot"} or figure.quality_score < 55,
        "created_at": iso(figure.created_at) if hasattr(figure, "created_at") else None,
    }


def collection_out(collection: Collection, paper_count: int = 0) -> dict[str, Any]:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "color": collection.color,
        "paper_count": paper_count,
        "created_at": iso(collection.created_at),
    }


def knowledge_out(
    item: KnowledgeItem,
    paper_title: str | None = None,
    meta: KnowledgeMeta | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "kind": item.kind,
        "tags": item.tags or [],
        "pinned": item.pinned,
        "project_id": item.project_id,
        "source_paper_id": item.source_paper_id,
        "source_paper_title": paper_title,
        "source_page": item.source_page,
        "source_quote": item.source_quote,
        "auto_tags": meta.auto_tags if meta else [],
        "cluster_key": meta.cluster_key if meta else "",
        "cluster_label": meta.cluster_label if meta else "",
        "version": meta.version if meta else 1,
        "duplicate_of": meta.duplicate_of if meta else None,
        "search_score": round(score, 4) if score is not None else None,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def knowledge_version_out(version: KnowledgeVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version": version.version,
        "title": version.title,
        "content": version.content,
        "kind": version.kind,
        "tags": version.tags or [],
        "note": version.note,
        "changed_fields": version.changed_fields or [],
        "created_at": iso(version.created_at),
    }


def link_out(link: KnowledgeLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "source_type": link.source_type,
        "source_id": link.source_id,
        "target_type": link.target_type,
        "target_id": link.target_id,
        "relation": link.relation,
        "note": link.note,
        "created_at": iso(link.created_at),
    }


def project_out(project: Project, counts: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "goal": project.goal,
        "status": project.status,
        "progress": project.progress,
        "color": project.color,
        "counts": counts or {},
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


def project_item_out(item: ProjectItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "kind": item.kind,
        "ref_id": item.ref_id,
        "title": item.title,
        "content": item.content,
        "meta": item.meta or {},
        "created_at": iso(item.created_at),
    }


def conversation_out(conversation: Conversation, message_count: int = 0, preview: str | None = None) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "mode": conversation.mode,
        "scope_type": conversation.scope_type,
        "scope_ids": conversation.scope_ids or [],
        "project_id": conversation.project_id,
        "archived": conversation.archived,
        "message_count": message_count,
        "preview": preview,
        "created_at": iso(conversation.created_at),
        "updated_at": iso(conversation.updated_at),
    }


def message_out(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "citations": message.citations or [],
        "mode": message.mode,
        "model": message.model,
        "created_at": iso(message.created_at),
        "agent_run_id": message.agent_run_id,
    }


def run_out(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "goal": run.goal,
        "mode": run.mode,
        "status": run.status,
        "provider": run.provider,
        "error": run.error,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }


def step_out(step: AgentStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "index": step.index,
        "type": step.type,
        "tool": step.tool_name,
        "input": step.input or {},
        "summary": step.output_summary,
        "status": step.status,
        "duration_ms": step.duration_ms,
        "started_at": iso(step.started_at),
        "finished_at": iso(step.finished_at),
    }


def export_out(record: ExportRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "title": record.title,
        "format": record.format,
        "filename": record.filename,
        "size_bytes": record.size_bytes,
        "created_at": iso(record.created_at),
        "download_url": f"/api/exports/{record.id}/download",
    }


def settings_out(settings_row: UserSettings) -> dict[str, Any]:
    return {
        "theme": settings_row.theme,
        "language": settings_row.language,
        "reading_font_size": settings_row.reading_font_size,
        "reading_width": settings_row.reading_width,
        "default_summary_mode": settings_row.default_summary_mode,
        "translation_language": settings_row.translation_language,
        "translation_style": settings_row.translation_style,
        "model_provider": settings_row.model_provider,
        "model_base_url": settings_row.model_base_url,
        "model_name": settings_row.model_name,
        "temperature": settings_row.temperature,
        "max_tokens": settings_row.max_tokens,
        "onboarding_completed": settings_row.onboarding_completed,
        "privacy": settings_row.privacy or {},
        "has_api_key": bool(settings_row.api_key_encrypted),
    }

EVIDENCE_TYPE_LABELS = {
    "direct": "原文直接证据",
    "shared": "多篇论文共同支持",
    "inferred": "AI 基于证据的推导",
    "hypothesis": "AI 研究假设",
    "insufficient": "证据不足",
    "external": "需要外部验证",
}


def evidence_out(evidence: Evidence, paper_title: str | None = None, context: dict | None = None) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "paper_id": evidence.paper_id,
        "paper_title": paper_title,
        "chunk_id": evidence.chunk_id,
        "analysis_id": evidence.analysis_id,
        "page": evidence.page,
        "section": evidence.section,
        "quote": evidence.quote,
        "claim": evidence.claim,
        "evidence_type": evidence.evidence_type,
        "type_label": EVIDENCE_TYPE_LABELS.get(evidence.evidence_type, evidence.evidence_type),
        "confidence": evidence.confidence,
        "verified": evidence.verified,
        "verification_note": evidence.verification_note,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "can_locate": bool(evidence.paper_id and evidence.page),
        "created_at": iso(evidence.created_at),
        "meta": evidence.meta or {},
        "source_label": (context or {}).get("source_label"),
        "source_title": (context or {}).get("source_title"),
        "source_excerpt": (context or {}).get("source_excerpt"),
        "source_url": (context or {}).get("source_url"),
        "source_available": bool((context or {}).get("source_available")),
        "gap_reason": (context or {}).get("gap_reason"),
    }

def insight_out(insight: ResearchInsight) -> dict[str, Any]:
    return {
        "id": insight.id,
        "kind": insight.kind,
        "title": insight.title,
        "scope_type": insight.scope_type,
        "paper_ids": insight.paper_ids or [],
        "data": insight.data or {},
        "citations": insight.citations or [],
        "local": insight.local,
        "model": insight.model,
        "analysis_id": insight.analysis_id,
        "created_at": iso(insight.created_at),
    }

def intelligence_report_out(report: IntelligenceReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "kind": report.kind,
        "scope_type": report.scope_type,
        "scope_id": report.scope_id,
        "scope_label": report.scope_label,
        "paper_ids": report.paper_ids or [],
        "data": report.data or {},
        "citations": report.citations or [],
        "local": report.local,
        "model": report.model,
        "created_at": iso(report.created_at),
    }

def task_out(task: AgentTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "conversation_id": task.conversation_id,
        "run_id": task.run_id,
        "user_message_id": task.user_message_id,
        "result_message_id": task.result_message_id,
        "goal": task.goal,
        "mode": task.mode,
        "scope_type": task.scope_type,
        "scope_ids": task.scope_ids or [],
        "status": task.status,
        "plan": task.plan or [],
        "plan_source": task.plan_source,
        "plan_confirmed": task.plan_confirmed,
        "progress": task.progress,
        "current_step": task.current_step,
        "self_check": task.self_check or {},
        "error": task.error,
        "provider": task.provider,
        "rerun_of": task.rerun_of,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
        "finished_at": iso(task.finished_at),
    }

def artifact_out(artifact: AcademicArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "title": artifact.title,
        "scope_type": artifact.scope_type,
        "scope_ids": artifact.scope_ids or [],
        "paper_ids": artifact.paper_ids or [],
        "content": artifact.content,
        "citations": artifact.citations or [],
        "evidence_table": artifact.evidence_table or [],
        "scope_statement": artifact.scope_statement,
        "local": artifact.local,
        "model": artifact.model,
        "quality_score": artifact.quality_score,
        "quality_status": artifact.quality_status,
        "knowledge_item_ids": artifact.knowledge_item_ids or [],
        "knowledge_saved_at": iso(artifact.knowledge_saved_at),
        "knowledge_saved": bool(artifact.knowledge_item_ids),
        "created_at": iso(artifact.created_at),
        "updated_at": iso(artifact.updated_at),
    }


def quality_out(report: ArtifactQualityReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "id": report.id,
        "status": report.status,
        "score": report.score,
        "issues": report.issues or [],
        "summary": report.summary,
        "checked_at": iso(report.checked_at),
    }

def processing_job_out(job: ProcessingJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "paper_id": job.paper_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "updated_at": iso(job.updated_at),
    }