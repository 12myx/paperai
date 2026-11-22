"""Conversation streaming, history and agent run inspection."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AgentRun, AgentStep, AgentTask, Conversation, Message, Project, User, utcnow
from ..schemas import AgentTaskPlanRequest, AgentTaskPlanUpdate, ChatStreamRequest, ConfirmActionRequest, ConversationUpdate
from ..serializers import conversation_out, message_out, run_out, step_out, task_out
from ..services.agent import ChatRequest, confirm_action, resolve_scope, stream_chat
from ..services.actions import ActionError, action_status, claim_action, finish_action
from ..services.tools import WRITE_TOOLS
from ..services import agent_tasks
from ..services.resource_usage import list_run_usage
from ..services.llm import resolve_model_config

router = APIRouter(tags=["chat"])

@router.post("/chat/stream")
async def chat_stream(payload: ChatStreamRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    request = ChatRequest(
        message=payload.message,
        conversation_id=payload.conversation_id,
        mode=payload.mode,
        scope_type=payload.scope_type,
        scope_ids=payload.scope_ids,
        project_id=payload.project_id,
        knowledge_ids=payload.knowledge_ids,
        image_ids=payload.image_ids,
        artifact_ids=payload.artifact_ids,
        exclude_ids=payload.exclude_ids,
        auto_retrieval=payload.auto_retrieval,
        auto_approve_writes=payload.auto_approve_writes,
    )
    return StreamingResponse(
        stream_chat(db, user, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
def list_conversations(
    query: str = "",
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Conversation).where(Conversation.user_id == user.id, Conversation.archived.is_(False))
    if query.strip():
        statement = statement.where(Conversation.title.ilike(f"%{query.strip()}%"))
    conversations = list(db.execute(statement.order_by(Conversation.updated_at.desc()).limit(limit)).scalars().all())
    result = []
    for conversation in conversations:
        count = db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        ).scalar() or 0
        last = db.execute(
            select(Message).where(Message.conversation_id == conversation.id, Message.role == "assistant").order_by(Message.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        result.append(conversation_out(conversation, count, (last.content[:160] if last else None)))
    return {"items": result}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在或无权访问")
    messages = list(
        db.execute(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)).scalars().all()
    )
    return {"conversation": conversation_out(conversation, len(messages)), "messages": [message_out(m) for m in messages]}


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str, payload: ConversationUpdate,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在或无权访问")
    if payload.title is not None:
        conversation.title = payload.title.strip()[:290] or conversation.title
    if payload.archived is not None:
        conversation.archived = payload.archived
    db.commit()
    return {"conversation": conversation_out(conversation)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在或无权访问")
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@router.get("/agent/runs")
def list_runs(
    conversation_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AgentRun).where(AgentRun.user_id == user.id)
    if conversation_id:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    runs = list(db.execute(statement.order_by(AgentRun.started_at.desc()).limit(limit)).scalars().all())
    return {"items": [run_out(run) for run in runs]}


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    steps = list(db.execute(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.index)).scalars().all())
    return {"run": run_out(run), "steps": [step_out(step) for step in steps]}


@router.get("/agent/runs/{run_id}/resources")
def get_run_resources(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "研究记录不存在或无权访问")
    return {"items": list_run_usage(db, user, run_id)}


@router.get("/agent/actions/{action_id}")
def get_action_status(action_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    record = action_status(db, user.id, action_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "操作记录不存在或无权访问")
    return {"action": record}


@router.post("/agent/actions/confirm")
async def confirm(payload: ConfirmActionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.tool not in WRITE_TOOLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该操作不需要确认或不被允许")
    if not payload.action_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "确认令牌缺失，请重新发起操作")
    try:
        row = claim_action(db, user.id, payload.tool, payload.args, payload.action_id)
    except ActionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    try:
        result = await confirm_action(db, user, payload.tool, payload.args)
    except Exception as exc:  # noqa: BLE001
        finish_action(db, row.id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:800]}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"操作执行失败：{exc}") from exc
    finish_action(db, row.id, status="succeeded", summary=str(result.get("summary") or "")[:1000])
    return {"result": result, "action": {"action_id": row.id, "status": "succeeded"}}

@router.post("/agent/tasks/plan")
async def plan_task(
    payload: AgentTaskPlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "任务目标不能为空")
    papers = resolve_scope(db, user, payload.scope_type, payload.scope_ids)
    conversation = None
    if payload.conversation_id:
        conversation = db.get(Conversation, payload.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在或无权访问")
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        if project is None or project.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在或无权访问")
    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            title=message[:60],
            mode=payload.mode,
            scope_type=payload.scope_type,
            scope_ids=payload.scope_ids,
            project_id=payload.project_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    plan, plan_source = await agent_tasks.build_plan_with_model(
        message, payload.mode, papers, resolve_model_config(db, user)
    )
    task = agent_tasks.create_task(
        db,
        user,
        goal=message,
        mode=payload.mode,
        scope_type=payload.scope_type,
        scope_ids=list(payload.scope_ids or []),
        conversation_id=conversation.id,
        plan=plan,
        plan_source=plan_source,
        status="queued",
        plan_confirmed=False,
    )
    return {
        "task": task_out(task),
        "plan": plan,
        "conversation_id": conversation.id,
        "is_complex": agent_tasks.is_complex(message, payload.mode, len(papers)),
        "paper_count": len(papers),
    }


@router.get("/agent/tasks")
def list_tasks(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(40, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AgentTask).where(AgentTask.user_id == user.id)
    if status_filter:
        statement = statement.where(AgentTask.status == status_filter)
    tasks = list(
        db.execute(statement.order_by(AgentTask.created_at.desc()).limit(limit)).scalars().all()
    )
    return {"items": [task_out(task) for task in tasks]}


@router.get("/agent/tasks/{task_id}")
def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    steps = list(
        db.execute(select(AgentStep).where(AgentStep.run_id == task.run_id).order_by(AgentStep.index)).scalars().all()
    ) if task.run_id else []
    result = db.get(Message, task.result_message_id) if task.result_message_id else None
    return {
        "task": task_out(task),
        "steps": [step_out(step) for step in steps],
        "result_message": message_out(result) if result else None,
    }


@router.patch("/agent/tasks/{task_id}/plan")
def update_task_plan(
    task_id: str,
    payload: AgentTaskPlanUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    try:
        plan = agent_tasks.apply_plan_update(task, payload.plan)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.commit()
    db.refresh(task)
    return {"task": task_out(task), "plan": plan}


@router.post("/agent/tasks/{task_id}/execute")
def execute_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    if task.status != "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, f"任务当前状态为 {task.status}，不能开始执行")
    claimed = db.execute(
        update(AgentTask)
        .where(AgentTask.id == task_id, AgentTask.user_id == user.id, AgentTask.status == "queued")
        .values(status="running", updated_at=utcnow())
    )
    db.commit()
    if claimed.rowcount != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "任务已被其他执行器接管或状态已变化")
    request = ChatRequest(
        message=task.goal,
        conversation_id=task.conversation_id,
        mode=task.mode,
        scope_type=task.scope_type,
        scope_ids=list(task.scope_ids or []),
        task_id=task.id,
    )
    return StreamingResponse(
        stream_chat(db, user, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/tasks/{task_id}/pause")
def pause_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    if task.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"只有运行中的任务可以暂停（当前 {task.status}）")
    task.status = "paused"
    task.updated_at = utcnow()
    db.commit()
    return {"task": task_out(task)}


@router.post("/agent/tasks/{task_id}/resume")
def resume_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    if task.status != "paused":
        raise HTTPException(status.HTTP_409_CONFLICT, f"只有暂停中的任务可以继续（当前 {task.status}）")
    task.status = "running"
    task.updated_at = utcnow()
    db.commit()
    return {"task": task_out(task)}


@router.post("/agent/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    if task.status in {"completed", "failed", "cancelled"}:
        return {"task": task_out(task)}
    task.status = "cancelled"
    task.finished_at = utcnow()
    task.updated_at = utcnow()
    db.commit()
    return {"task": task_out(task)}


@router.post("/agent/tasks/{task_id}/rerun")
async def rerun_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(AgentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    papers = resolve_scope(db, user, task.scope_type, list(task.scope_ids or []))
    plan, plan_source = await agent_tasks.build_plan_with_model(
        task.goal, task.mode, papers, resolve_model_config(db, user)
    )
    new_task = agent_tasks.create_task(
        db,
        user,
        goal=task.goal,
        mode=task.mode,
        scope_type=task.scope_type,
        scope_ids=list(task.scope_ids or []),
        conversation_id=task.conversation_id,
        plan=plan,
        plan_source=plan_source,
        status="queued",
        plan_confirmed=False,
        rerun_of=task.id,
    )
    return {"task": task_out(new_task)}