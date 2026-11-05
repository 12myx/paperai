"""Export research artefacts as real downloadable files."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ExportRecord, KnowledgeItem, Paper, Project, ProjectItem, User
from ..schemas import ExportRequest
from ..serializers import export_out
from ..services import analysis
from ..services.export import build_export
from ..services.llm import LLMError, resolve_model_config
from ..services.storage import safe_filename, storage

router = APIRouter(prefix="/exports", tags=["exports"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
}


@router.get("")
def list_exports(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    records = list(
        db.execute(select(ExportRecord).where(ExportRecord.user_id == user.id).order_by(ExportRecord.created_at.desc()).limit(80)).scalars().all()
    )
    return {"items": [export_out(r) for r in records]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_export(payload: ExportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.format.lower() not in MEDIA_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "不支持的导出格式")
    content = (payload.content or "").strip()
    title = payload.title.strip() or "PaperLens export"
    meta: dict = {"kind": payload.kind}

    if not content and payload.paper_id:
        paper = db.get(Paper, payload.paper_id)
        if paper is None or paper.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "论文不存在或无权访问")
        config = resolve_model_config(db, user)
        try:
            content, citations, local = await analysis.generative_summary(db, user, config, paper, "full")
        except LLMError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        title = payload.title if payload.title != "PaperLens report" else f"{paper.title} — 论文总结"
        meta.update({"paper_id": paper.id, "citations": [c["key"] for c in citations], "local": local, "model": config.model if config else "local"})

    if not content and payload.knowledge_ids:
        items = list(
            db.execute(select(KnowledgeItem).where(KnowledgeItem.user_id == user.id, KnowledgeItem.id.in_(payload.knowledge_ids))).scalars().all()
        )
        if not items:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到可导出的知识条目")
        blocks = [f"# 知识片段导出\n\n共 {len(items)} 条 · 导出于 {datetime.now():%Y-%m-%d %H:%M}\n"]
        for item in items:
            blocks.append(f"## {item.title}\n\n类型：{item.kind} · 标签：{', '.join(item.tags or []) or '无'}\n\n{item.content}\n")
            if item.source_quote:
                blocks.append(f"> 原文引用：{item.source_quote}\n")
        content = "\n".join(blocks)
        title = title if title != "PaperLens report" else "个人知识库导出"
        meta["knowledge_count"] = len(items)

    if not content and payload.project_id:
        project = db.get(Project, payload.project_id)
        if project is None or project.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
        items = list(db.execute(select(ProjectItem).where(ProjectItem.project_id == project.id)).scalars().all())
        blocks = [f"# {project.name}\n\n{project.description or ''}\n\n**研究目标**：{project.goal or '未设置'}\n"]
        for item in items:
            blocks.append(f"## {item.title or item.kind}\n\n{item.content or ''}\n")
        content = "\n".join(blocks)
        title = title if title != "PaperLens report" else project.name
        meta["project_id"] = project.id

    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "没有可导出的内容：请提供 content、paper_id、knowledge_ids 或 project_id")

    try:
        data, ext = build_export(payload.format, title, content, meta)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    filename = f"{safe_filename(title, 'paperlens-export')}.{ext}"
    relative = storage.save_export(user.id, filename, data)
    record = ExportRecord(
        user_id=user.id, kind=payload.kind, title=title[:290], format=ext,
        filename=filename, path=relative, size_bytes=len(data), meta=meta,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"export": export_out(record)}


@router.get("/{export_id}/download")
def download(export_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    record = db.get(ExportRecord, export_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导出文件不存在或无权访问")
    try:
        path = storage.abs_path(record.path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件路径无效") from exc
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件已被删除")
    return FileResponse(path, media_type=MEDIA_TYPES.get(record.format, "application/octet-stream"), filename=record.filename)


@router.delete("/{export_id}")
def delete_export(export_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    record = db.get(ExportRecord, export_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导出文件不存在或无权访问")
    db.delete(record)
    db.commit()
    return {"ok": True}
