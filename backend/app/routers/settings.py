"""User preferences, model configuration and data management."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..db import get_db
from ..deps import get_current_user, get_user_settings
from ..models import (
    AgentRun, AgentStep, Annotation, Chunk, Collection, CollectionPaper, Conversation,
    ExportRecord, Figure, KnowledgeItem, KnowledgeLink, Message, Paper, PaperPage,
    Project, ProjectItem, Section, UsageEvent, User, UserSettings, utcnow,
)
from ..schemas import AccountDeleteRequest, ModelKeyRequest, SettingsUpdate
from ..security import encrypt_secret, verify_password
from ..serializers import export_out, settings_out, user_out
from ..services.llm import LLMClient, LLMError, ModelConfig, model_public_status
from ..services.storage import storage

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = get_user_settings(db, user)
    return {"settings": settings_out(row), "model": model_public_status(db, user), "user": user_out(user)}


@router.patch("")
def update_settings(payload: SettingsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = get_user_settings(db, user)
    for field_name in (
        "theme", "language", "reading_font_size", "reading_width", "default_summary_mode",
        "translation_language", "translation_style", "model_provider", "model_base_url",
        "model_name", "temperature", "max_tokens", "onboarding_completed", "privacy",
    ):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(row, field_name, value)
    if row.temperature is not None:
        row.temperature = max(0.0, min(1.5, row.temperature))
    if row.max_tokens is not None:
        row.max_tokens = max(256, min(8000, row.max_tokens))
    if row.reading_font_size is not None:
        row.reading_font_size = max(12, min(26, row.reading_font_size))
    row.updated_at = utcnow()
    db.commit()
    return {"settings": settings_out(row), "model": model_public_status(db, user)}


@router.post("/model-key")
async def set_model_key(payload: ModelKeyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = get_user_settings(db, user)
    base_url = (payload.base_url or row.model_base_url or app_settings.deepseek_base_url).rstrip("/")
    model_name = (payload.model_name or row.model_name or app_settings.deepseek_model).strip()
    config = ModelConfig(
        provider=row.model_provider or "deepseek",
        base_url=base_url,
        api_key=payload.api_key.strip(),
        model=model_name,
        temperature=payload.temperature if payload.temperature is not None else row.temperature,
        max_tokens=16,
        source="user",
    )
    try:
        response = await LLMClient(config).complete([{"role": "user", "content": "ping"}], max_tokens=8, temperature=0.0)
        if response.get("content") is None:
            raise LLMError("模型返回为空")
    except LLMError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"模型连接测试失败：{exc}") from exc

    row.api_key_encrypted = encrypt_secret(payload.api_key.strip())
    row.model_base_url = base_url
    row.model_name = model_name
    if payload.temperature is not None:
        row.temperature = max(0.0, min(1.5, payload.temperature))
    row.updated_at = utcnow()
    db.commit()
    return {"ok": True, "model": model_public_status(db, user)}


@router.delete("/model-key")
def clear_model_key(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = get_user_settings(db, user)
    row.api_key_encrypted = None
    row.updated_at = utcnow()
    db.commit()
    return {"ok": True, "model": model_public_status(db, user)}


@router.get("/usage")
def usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    rows = db.execute(
        select(UsageEvent.kind, func.count(UsageEvent.id))
        .where(UsageEvent.user_id == user.id, UsageEvent.created_at >= since)
        .group_by(UsageEvent.kind)
    ).all()
    total_papers = db.execute(select(func.count(Paper.id)).where(Paper.user_id == user.id)).scalar() or 0
    total_pages = db.execute(select(func.sum(Paper.page_count)).where(Paper.user_id == user.id)).scalar() or 0
    storage_bytes = db.execute(select(func.sum(Paper.size_bytes)).where(Paper.user_id == user.id)).scalar() or 0
    return {
        "last_30_days": {kind: count for kind, count in rows},
        "papers": total_papers,
        "pages": int(total_pages),
        "storage_bytes": int(storage_bytes),
        "plan": user.plan,
    }


@router.post("/data-export")
async def export_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    papers = list(db.execute(select(Paper).where(Paper.user_id == user.id)).scalars().all())
    annotations = list(db.execute(select(Annotation).where(Annotation.user_id == user.id)).scalars().all())
    knowledge = list(db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)).scalars().all())
    projects = list(db.execute(select(Project).where(Project.user_id == user.id)).scalars().all())
    conversations = list(db.execute(select(Conversation).where(Conversation.user_id == user.id)).scalars().all())
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": user_out(user),
        "papers": [
            {"id": p.id, "title": p.title, "authors": p.authors, "year": p.year, "abstract": p.abstract,
             "tags": p.tags, "page_count": p.page_count, "status": p.status, "created_at": str(p.created_at)}
            for p in papers
        ],
        "annotations": [
            {"id": a.id, "paper_id": a.paper_id, "page": a.page_number, "color": a.color, "quote": a.quote, "note": a.note, "tags": a.tags}
            for a in annotations
        ],
        "knowledge": [
            {"id": k.id, "title": k.title, "content": k.content, "kind": k.kind, "tags": k.tags, "source_paper_id": k.source_paper_id}
            for k in knowledge
        ],
        "projects": [{"id": p.id, "name": p.name, "goal": p.goal, "description": p.description} for p in projects],
        "conversations": [
            {"id": c.id, "title": c.title, "mode": c.mode, "messages": [
                {"role": m.role, "content": m.content, "created_at": str(m.created_at)}
                for m in db.execute(select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)).scalars().all()
            ]}
            for c in conversations
        ],
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"paperlens-data-{user.id[:8]}-{datetime.now():%Y%m%d}.json"
    relative = storage.save_export(user.id, filename, data)
    record = ExportRecord(
        user_id=user.id, kind="data-export", title="账号数据导出", format="json",
        filename=filename, path=relative, size_bytes=len(data), meta={"scope": "account"},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"export": export_out(record)}


@router.delete("/account")
def delete_account(payload: AccountDeleteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.confirm != "DELETE":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请输入 DELETE 以确认删除账号")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码不正确")
    user_id = user.id
    for model in (AgentStep, AgentRun, Annotation, Chunk, Figure, KnowledgeLink, KnowledgeItem,
                  ProjectItem, Project, CollectionPaper, Collection, Section, PaperPage,
                  ExportRecord, Message, Conversation, UserSettings, UsageEvent):
        if hasattr(model, "user_id"):
            db.execute(delete(model).where(model.user_id == user_id))
    paper_ids = [p.id for p in db.execute(select(Paper).where(Paper.user_id == user_id)).scalars().all()]
    if paper_ids:
        db.execute(delete(Chunk).where(Chunk.paper_id.in_(paper_ids)))
        db.execute(delete(Annotation).where(Annotation.paper_id.in_(paper_ids)))
        db.execute(delete(Figure).where(Figure.paper_id.in_(paper_ids)))
        db.execute(delete(Section).where(Section.paper_id.in_(paper_ids)))
        db.execute(delete(PaperPage).where(PaperPage.paper_id.in_(paper_ids)))
        db.execute(delete(Paper).where(Paper.id.in_(paper_ids)))
    db.execute(delete(UsageEvent).where(UsageEvent.user_id == user_id))
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    storage.delete_user(user_id)
    return {"ok": True}