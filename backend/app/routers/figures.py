"""Extracted figures, tables and their AI explanations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Figure, Paper, User
from ..schemas import FigureUpdate
from ..serializers import figure_out
from ..services.llm import LLMClient, LLMError, resolve_model_config
from ..services.storage import storage

router = APIRouter(prefix="/figures", tags=["figures"])


@router.get("")
def list_figures(
    paper_id: str | None = None,
    saved: bool | None = None,
    kind: str | None = None,
    query: str = "",
    limit: int = Query(120, ge=1, le=400),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Figure).where(Figure.user_id == user.id)
    if paper_id:
        statement = statement.where(Figure.paper_id == paper_id)
    if saved is not None:
        statement = statement.where(Figure.saved == saved)
    if kind:
        statement = statement.where(Figure.kind == kind)
    figures = list(db.execute(statement.order_by(Figure.paper_id, Figure.order_index).limit(limit)).scalars().all())
    if query:
        needle = query.lower()
        figures = [f for f in figures if needle in ((f.caption or "") + (f.note or "")).lower()]
    titles = {
        paper.id: paper.title
        for paper in db.execute(select(Paper).where(Paper.user_id == user.id)).scalars().all()
    }
    return {"items": [figure_out(f, titles.get(f.paper_id)) for f in figures]}


@router.get("/{figure_id}/image")
def figure_image(figure_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    figure = db.get(Figure, figure_id)
    if figure is None or figure.user_id != user.id or not figure.image_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在或无权访问")
    try:
        path = storage.abs_path(figure.image_path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片路径无效") from exc
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片文件不存在")
    media = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    return FileResponse(path, media_type=media)


@router.patch("/{figure_id}")
def update_figure(figure_id: str, payload: FigureUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    figure = db.get(Figure, figure_id)
    if figure is None or figure.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在或无权访问")
    if payload.note is not None:
        figure.note = payload.note[:4000]
    if payload.saved is not None:
        figure.saved = payload.saved
    db.commit()
    paper = db.get(Paper, figure.paper_id)
    return {"figure": figure_out(figure, paper.title if paper else None)}


@router.post("/{figure_id}/explain")
async def explain_figure(figure_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    figure = db.get(Figure, figure_id)
    if figure is None or figure.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在或无权访问")
    config = resolve_model_config(db, user)
    paper = db.get(Paper, figure.paper_id)
    if config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "model_required", "message": "图表解释需要生成式模型，请先在设置中配置 DeepSeek API Key。"},
        )
    prompt = (
        f"论文：{paper.title if paper else '未知'}\n第 {figure.page_number} 页 {figure.kind}\n"
        f"图注：{figure.caption or '无'}\n表格数据：\n{(figure.table_markdown or '')[:3000]}\n\n"
        "请解释这个图表：展示什么、关键趋势/数值、作者想支持什么结论、以及读图时需要注意的局限。"
        "不要编造图中不存在的数值。"
    )
    try:
        response = await LLMClient(config).complete(
            [{"role": "system", "content": "你是严谨的科研图表解读助手。"}, {"role": "user", "content": prompt}],
            temperature=0.2,
        )
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    figure.ai_explanation = response["content"]
    db.commit()
    return {"figure": figure_out(figure, paper.title if paper else None)}
