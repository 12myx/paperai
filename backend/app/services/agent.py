"""Agent orchestration: planning, real tool execution, streaming and persistence."""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AgentRun,
    AgentStep,
    AgentTask,
    CollectionPaper,
    Conversation,
    Message,
    Paper,
    ProjectItem,
    UsageEvent,
    User,
    utcnow,
)
from . import analysis
from . import agent_tasks
from .evidence import harvest_citations, insufficient_for_answer
from .llm import LLMClient, LLMError, ModelConfig, resolve_model_config, system_prompt
from .rag import search as rag_search
from .tools import TOOL_SPECS, ToolError, ToolRunner, compact_tool_payload

MAX_ROUNDS = 5


@dataclass
class ChatRequest:
    message: str
    conversation_id: str | None = None
    mode: str = "quick"
    scope_type: str = "all"
    scope_ids: list[str] = field(default_factory=list)
    project_id: str | None = None
    auto_approve_writes: bool = False
    task_id: str | None = None


def resolve_scope(db: Session, user: User, scope_type: str, scope_ids: list[str]) -> list[Paper]:
    if scope_type == "collection" and scope_ids:
        ids = db.execute(
            select(CollectionPaper.paper_id).where(CollectionPaper.collection_id.in_(scope_ids))
        ).scalars().all()
        if not ids:
            return []
        return list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all())
    if scope_type == "project" and scope_ids:
        refs = db.execute(
            select(ProjectItem.ref_id).where(
                ProjectItem.project_id.in_(scope_ids), ProjectItem.kind == "paper", ProjectItem.user_id == user.id
            )
        ).scalars().all()
        refs = [r for r in refs if r]
        if not refs:
            return []
        return list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(refs))).scalars().all())
    if scope_type == "papers" and scope_ids:
        return list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(scope_ids))).scalars().all())
    return list(
        db.execute(
            select(Paper).where(Paper.user_id == user.id).order_by(Paper.created_at.desc()).limit(60)
        ).scalars().all()
    )


def sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _chunk_text(text: str, size: int = 42) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _short(title: str, limit: int = 46) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def compose_local_answer(question: str, citations: list[dict], mode: str, papers: list[Paper]) -> str:
    header = analysis.LOCAL_BANNER
    if not citations:
        return header + (
            "## 未检索到可支撑回答的原文\n\n"
            "在所选范围内没有找到与你问题相关的论文片段。可能的原因：\n"
            "1. 资料库中还没有已解析完成的论文；\n"
            "2. 研究范围选择过窄；\n"
            "3. 问题使用的术语与论文表述差异较大，可换用论文中的英文关键词重试。\n\n"
            "建议先上传论文，或在输入框上方扩大研究范围。"
        )

    grouped: dict[str, list[dict]] = {}
    for citation in citations:
        grouped.setdefault(citation["paper_id"], []).append(citation)

    if mode == "multi_paper" or len(grouped) > 1:
        lines = [header, "## 分论文证据摘要\n"]
        for items in grouped.values():
            lines.append(f"### {_short(items[0]['paper_title'], 80)}（{items[0].get('paper_year') or 'n.d.'}）")
            for citation in items[:3]:
                for sentence in analysis.pick_sentences(citation["quote"], question, 2):
                    lines.append(f"- {sentence} [{citation['key']}] · 第 {citation['page']} 页 · {citation['section']}")
            lines.append("")
        lines.append("### 跨论文观察")
        lines.append(
            f"本次检索覆盖 {len(grouped)} 篇论文、{len(citations)} 个片段。"
            "本地模式只并列呈现各论文的原文要点，不做跨论文的优劣或因果判断；"
            "配置生成式模型后可获得对比分析。"
        )
        return "\n".join(lines)

    lines = [header, f"## 与问题最相关的原文证据\n《{_short(citations[0]['paper_title'], 70)}》\n"]
    for citation in citations[:5]:
        for sentence in analysis.pick_sentences(citation["quote"], question, 2):
            lines.append(f"- {sentence} [{citation['key']}] · 第 {citation['page']} 页 · {citation['section']}")
    lines.append("")
    if mode == "critical":
        lines.append("### 证据边界")
        lines.append("- 以上为原文陈述，不代表已经过独立复现或同行验证。")
        lines.append("- 评估方法合理性需要结合实验设置、基线选择与数据规模，本地模式无法给出因果判断。")
        lines.append("- 建议在阅读器中打开对应页面，核对上下文与图表后再形成结论。")
    elif mode == "explore":
        lines.append("### 可继续追问的方向")
        lines.append("- 这些片段是否指向同一研究缺口？可在资料库中检索相关综述与后续工作。")
        lines.append("- 方法在不同数据集上的表现是否一致？请查看实验章节的完整表格。")
    else:
        lines.append("### 说明")
        lines.append("以上内容由检索排序与句子抽取生成，未经过生成式改写；点击引用可回到原文位置核对。")
    return "\n".join(lines)


def _should_compare(message: str, papers: list[Paper]) -> bool:
    return len(papers) >= 2 and bool(re.search(r"对比|比较|差异|区别|compare|comparison|versus", message, re.I))


def _should_gap(message: str) -> bool:
    return bool(re.search(r"空白|缺口|未解决|未来方向|研究机会|gap|open problem|future work", message, re.I))


def _should_report(message: str) -> bool:
    return bool(re.search(r"报告|综述|report|survey|文献回顾", message, re.I))


def _should_summary(message: str) -> bool:
    return bool(re.search(r"总结|概括|摘要|讲了什么|主要贡献|summar|overview|contribution", message, re.I))


def _should_figures(message: str) -> bool:
    return bool(re.search(r"图表|图片|figure|table|示意图", message, re.I))


def _should_translate(message: str) -> bool:
    return bool(re.search(r"翻译|translate|译成|中译", message, re.I))


def _should_save(message: str) -> bool:
    return bool(re.search(r"保存|收藏|记到|存入|知识库|save (?:this|it)", message, re.I))


async def stream_chat(db: Session, user: User, request: ChatRequest) -> AsyncIterator[str]:
    message_text = (request.message or "").strip()
    if not message_text:
        yield sse({"type": "error", "message": "消息不能为空"})
        return

    task: AgentTask | None = None
    conversation: Conversation | None = None
    user_message: Message | None = None
    run: AgentRun | None = None

    if request.task_id:
        task = db.get(AgentTask, request.task_id)
        if task is None or task.user_id != user.id:
            yield sse({"type": "error", "message": "任务不存在或无权访问"})
            return
        if task.status in {"cancelled", "completed", "failed"}:
            yield sse({"type": "error", "message": f"任务当前状态为 {task.status}，不能执行"})
            return
        message_text = task.goal
        request.mode = task.mode
        request.scope_type = task.scope_type
        request.scope_ids = list(task.scope_ids or [])
        if task.conversation_id:
            conversation = db.get(Conversation, task.conversation_id)
            if conversation is None or conversation.user_id != user.id:
                yield sse({"type": "error", "message": "会话不存在或无权访问"})
                return
    else:
        conversation = None
        if request.conversation_id:
            conversation = db.get(Conversation, request.conversation_id)
            if conversation is None or conversation.user_id != user.id:
                yield sse({"type": "error", "message": "会话不存在或无权访问"})
                return

    papers = resolve_scope(db, user, request.scope_type, request.scope_ids)
    scope_ids = [p.id for p in papers] if request.scope_type != "all" else None
    config = resolve_model_config(db, user)

    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            title=message_text[:60],
            mode=request.mode,
            scope_type=request.scope_type,
            scope_ids=request.scope_ids,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    else:
        conversation.mode = request.mode
        conversation.scope_type = request.scope_type
        conversation.scope_ids = request.scope_ids
        conversation.updated_at = utcnow()
        db.commit()

    if task is not None and task.user_message_id:
        user_message = db.get(Message, task.user_message_id)
    if user_message is None:
        user_message = Message(conversation_id=conversation.id, role="user", content=message_text, mode=request.mode)
        db.add(user_message)
        db.commit()
        db.refresh(user_message)

    run = AgentRun(
        user_id=user.id, conversation_id=conversation.id, goal=message_text[:500],
        mode=request.mode, provider="deepseek" if config else "local", status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if task is None:
        plan = agent_tasks.build_plan(message_text, request.mode, papers)
        task = agent_tasks.create_task(
            db,
            user,
            goal=message_text,
            mode=request.mode,
            scope_type=request.scope_type,
            scope_ids=list(request.scope_ids or []),
            conversation_id=conversation.id,
            plan=plan,
            status="running",
            plan_confirmed=True,
        )
    else:
        if not task.plan:
            task.plan = agent_tasks.build_plan(message_text, request.mode, papers)
        task.status = "running"
        task.plan_confirmed = True
        task.error = None
    task.conversation_id = conversation.id
    task.user_message_id = user_message.id
    task.run_id = run.id
    task.provider = "deepseek" if config else "local"
    task.updated_at = utcnow()
    db.commit()

    yield sse(
        {
            "type": "start",
            "conversation_id": conversation.id,
            "run_id": run.id,
            "task_id": task.id,
            "message_id": user_message.id,
            "provider": "deepseek" if config else "local",
            "mode": request.mode,
            "plan": task.plan,
            "scope": {
                "type": request.scope_type,
                "paper_count": len(papers),
                "papers": [{"id": p.id, "title": p.title} for p in papers[:20]],
            },
        }
    )
    yield sse(
        {
            "type": "plan",
            "task_id": task.id,
            "plan": task.plan,
            "plan_source": task.plan_source,
            "plan_confirmed": task.plan_confirmed,
            "auto_execute": True,
        }
    )

    runner = ToolRunner(db, user, config, scope_ids, allow_writes=request.auto_approve_writes)
    collected: list[dict] = []
    actions: list[dict] = []
    answer = ""
    state = {"step": 0}

    async def persist_step(name: str, args: dict, status: str, summary: str = "", duration_ms: int = 0) -> AgentStep:
        state["step"] += 1
        step = AgentStep(
            run_id=run.id, index=state["step"], type="tool", tool_name=name,
            input=args, status=status, output_summary=summary[:1500], duration_ms=duration_ms,
        )
        db.add(step)
        db.commit()
        return step

    try:
        # Give the UI a moment to register pause/cancel before the first tool.
        await asyncio.sleep(0.4)
        async for control in agent_tasks.control_events(db, task):
            yield sse(control)
        async for event in _run_agent(
            db, user, request, conversation, run, papers, config, runner, collected, actions, persist_step, task
        ):
            if event.get("type") == "answer":
                answer = event["text"]
            else:
                yield sse(event)
    except agent_tasks.TaskCancelled:
        task.status = "cancelled"
        task.finished_at = utcnow()
        run.status = "cancelled"
        run.finished_at = utcnow()
        db.commit()
        yield sse({"type": "cancelled", "task_id": task.id, "message": "任务已取消，未写入新消息。"})
        return
    except asyncio.CancelledError:
        task.status = "cancelled"
        task.finished_at = utcnow()
        run.status = "cancelled"
        run.finished_at = utcnow()
        db.commit()
        raise
    except LLMError as exc:
        async for control in agent_tasks.control_events(db, task):
            yield sse(control)
        fallback_note = f"> 模型调用失败：{exc}\n> 已切换到本地抽取模式，以下内容仅来自检索到的原文。\n\n"
        citations = rag_search(db, user.id, message_text, scope_ids, top_k=8)
        answer = fallback_note + compose_local_answer(message_text, citations, request.mode, papers)
        collected.extend(citations)
        yield sse({"type": "notice", "message": str(exc), "level": "warning"})
        for piece in _chunk_text(answer):
            yield sse({"type": "delta", "text": piece})
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.error = str(exc)[:1000]
        task.finished_at = utcnow()
        run.status = "failed"
        run.error = str(exc)[:1000]
        run.finished_at = utcnow()
        db.commit()
        yield sse({"type": "error", "message": f"研究任务执行失败：{exc}"})
        return

    # A pause/cancel that arrived during the final tool/model call still wins.
    try:
        async for control in agent_tasks.control_events(db, task):
            yield sse(control)
    except agent_tasks.TaskCancelled:
        task.status = "cancelled"
        task.finished_at = utcnow()
        run.status = "cancelled"
        run.finished_at = utcnow()
        db.commit()
        yield sse({"type": "cancelled", "task_id": task.id, "message": "任务已取消，未写入新消息。"})
        return

    db.refresh(task)
    if task.status in {"cancelled", "failed"}:
        yield sse({"type": "cancelled", "task_id": task.id, "message": "任务已取消。"})
        return

    unique: dict[str, dict] = {}
    for citation in collected:
        if citation.get("chunk_id") and citation["chunk_id"] not in unique:
            unique[citation["chunk_id"]] = citation
    citations = list(unique.values())[:14]

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        citations=citations,
        mode=request.mode,
        model=config.model if config else "local-extractive",
        tokens=int(len(answer) / 2.6),
        agent_run_id=run.id,
    )
    db.add(assistant_message)
    db.flush()

    evidence_ids: list[str] = []
    try:
        harvested, _skipped = harvest_citations(
            db,
            user,
            citations,
            source_type="message",
            source_id=assistant_message.id,
            analysis_kind=request.mode,
            claim=message_text[:300],
            insufficient_if_empty=False,
        )
        evidence_ids = [item.id for item in harvested]
        if not harvested:
            insufficient = insufficient_for_answer(
                db,
                user,
                answer=answer,
                source_type="message",
                source_id=assistant_message.id,
            )
            if insufficient is not None:
                evidence_ids = [insufficient.id]
    except Exception:  # noqa: BLE001 - evidence must never break the answer
        evidence_ids = []

    agent_tasks.mark_plan_step(task, None, "completed", "组织答案")
    db.commit()
    steps = list(
        db.execute(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.index)).scalars().all()
    )
    check = agent_tasks.self_check(message_text, answer, citations, steps, task.plan or [])
    task.self_check = check
    agent_tasks.complete_plan(task)
    task.status = "completed"
    task.result_message_id = assistant_message.id
    task.finished_at = utcnow()
    task.updated_at = utcnow()

    run.message_id = assistant_message.id
    run.status = "completed"
    run.finished_at = utcnow()
    db.add(UsageEvent(user_id=user.id, kind="chat", detail=f"mode={request.mode}; papers={len(papers)}"))
    conversation.updated_at = utcnow()
    db.commit()

    yield sse({"type": "self_check", "task_id": task.id, "self_check": check})
    yield sse(
        {
            "type": "done",
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "run_id": run.id,
            "task_id": task.id,
            "citations": citations,
            "actions": actions,
            "provider": "deepseek" if config else "local",
            "mode": request.mode,
            "content": answer,
            "evidence_count": len(evidence_ids),
            "evidence_ids": evidence_ids,
            "self_check": check,
            "plan": task.plan,
        }
    )


def _tool_label(name: str) -> str:
    return {
        "search_papers": "检索论文",
        "read_paper": "读取论文",
        "retrieve_chunks": "检索原文片段",
        "summarize_paper": "总结论文",
        "translate_content": "翻译内容",
        "compare_papers": "多论文对比",
        "extract_knowledge": "提取知识",
        "save_knowledge": "保存知识",
        "save_annotation": "保存批注",
        "extract_figures": "提取图表",
        "analyze_research_gap": "分析研究缺口",
        "generate_report": "生成研究报告",
        "export_document": "导出文件",
        "search_research_history": "检索历史",
        "research_intelligence": "研究情报",
    }.get(name, name)


def _safe_args(args: dict) -> dict:
    safe = {}
    for key, value in list(args.items())[:6]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value[:200] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key] = value[:6]
    return safe


async def _run_agent(db, user, request, conversation, run, papers, config, runner, collected, actions, persist_step, task) -> AsyncIterator[dict]:
    question = request.message
    mode = request.mode

    history = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at.desc())
            .limit(9)
        ).scalars().all()
    )[::-1]
    history = [m for m in history if m.content][:-1]

    if config is None:
        async for event in _local_pipeline(db, user, question, mode, papers, runner, persist_step, collected, actions, task):
            yield event
        return

    scope_line = (
        "当前研究范围：" + "、".join(f"《{p.title}》(id={p.id})" for p in papers[:12])
        if papers
        else "当前资料库为空，请提示用户上传论文。"
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt(mode)}]
    for item in history[-6:]:
        messages.append({"role": item.role, "content": item.content[:1800]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"{scope_line}\n\n用户任务：{question}\n\n"
                "如果任务涉及论文内容，必须先调用工具（retrieve_chunks / read_paper / summarize_paper 等）获取证据，再作答。"
                "引用只能使用工具返回的 [C#] 编号。"
            ),
        }
    )

    client = LLMClient(config)
    final_text = ""
    used_tools = False
    step_index = 0

    for _round in range(MAX_ROUNDS):
        async for control in agent_tasks.control_events(db, task):
            yield control
        response = await client.complete(messages, tools=TOOL_SPECS)
        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            final_text = response.get("content") or ""
            break
        used_tools = True
        messages.append({"role": "assistant", "content": response.get("content") or "", "tool_calls": tool_calls})
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name", "")
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            async for control in agent_tasks.control_events(db, task):
                yield control
            step_index += 1
            started = time.time()
            agent_tasks.mark_plan_step(task, name, "running")
            db.commit()
            step = await persist_step(name, args, "running")
            yield {
                "type": "step",
                "step": {"id": step.id, "index": step_index, "tool": name, "label": _tool_label(name), "status": "running", "input": _safe_args(args)},
            }
            try:
                result = await runner.run(name, args)
            except (ToolError, LLMError) as exc:
                step.status = "error"
                step.output_summary = str(exc)[:800]
                step.finished_at = utcnow()
                step.duration_ms = int((time.time() - started) * 1000)
                agent_tasks.mark_plan_step(task, name, "failed")
                db.commit()
                yield {"type": "step", "step": {"id": step.id, "index": step_index, "tool": name, "label": _tool_label(name), "status": "error", "summary": str(exc)[:400]}}
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps({"error": str(exc)}, ensure_ascii=False)})
                continue

            for citation in result.get("citations") or []:
                if citation.get("chunk_id") and citation["chunk_id"] not in {c.get("chunk_id") for c in collected}:
                    collected.append(citation)
            if result.get("pending") and result.get("action"):
                actions.append(result["action"])

            step.status = "pending" if result.get("pending") else "done"
            step.output_summary = (result.get("summary") or "")[:1500]
            step.finished_at = utcnow()
            step.duration_ms = int((time.time() - started) * 1000)
            agent_tasks.mark_plan_step(task, name, "completed")
            db.commit()
            yield {
                "type": "step",
                "step": {
                    "id": step.id, "index": step_index, "tool": name, "label": _tool_label(name),
                    "status": step.status, "summary": (result.get("summary") or "")[:600],
                    "duration_ms": step.duration_ms,
                    "citations": [c.get("key") for c in (result.get("citations") or [])][:8],
                },
            }
            if result.get("pending") and result.get("action"):
                yield {"type": "action", "action": result["action"]}
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": compact_tool_payload(result)})

    async for control in agent_tasks.control_events(db, task):
        yield control
    if not final_text:
        if used_tools:
            messages.append({"role": "user", "content": "请基于以上工具返回的真实证据，直接给出最终答案，使用 [C#] 标注引用。"})
            async for delta in client.stream(messages):
                async for control in agent_tasks.control_events(db, task):
                    yield control
                final_text += delta
                yield {"type": "delta", "text": delta}
        else:
            final_text = "模型没有返回内容，请重试或缩短问题。"
            for piece in _chunk_text(final_text):
                yield {"type": "delta", "text": piece}
    else:
        for piece in _chunk_text(final_text):
            yield {"type": "delta", "text": piece}

    yield {"type": "answer", "text": final_text}


async def _local_pipeline(db, user, question, mode, papers, runner, persist_step, collected, actions, task) -> AsyncIterator[dict]:
    """Deterministic tool routing used when no generative model is configured."""
    step_index = 0
    last: dict = {}

    async for control in agent_tasks.control_events(db, task):
        yield control

    async def run_tool(name: str, args: dict):
        nonlocal step_index
        async for control in agent_tasks.control_events(db, task):
            yield control
        step_index += 1
        started = time.time()
        agent_tasks.mark_plan_step(task, name, "running")
        db.commit()
        yield {"type": "step", "step": {"index": step_index, "tool": name, "label": _tool_label(name), "status": "running", "input": _safe_args(args)}}
        try:
            result = await runner.run(name, args)
        except (ToolError, LLMError) as exc:
            await persist_step(name, args, "error", str(exc))
            agent_tasks.mark_plan_step(task, name, "failed")
            db.commit()
            yield {"type": "step", "step": {"index": step_index, "tool": name, "label": _tool_label(name), "status": "error", "summary": str(exc)[:300]}}
            last["value"] = {"error": str(exc)}
            return
        for citation in result.get("citations") or []:
            if citation.get("chunk_id") and citation["chunk_id"] not in {c.get("chunk_id") for c in collected}:
                collected.append(citation)
        if result.get("pending") and result.get("action"):
            actions.append(result["action"])
            yield {"type": "action", "action": result["action"]}
        last["value"] = result
        duration = int((time.time() - started) * 1000)
        agent_tasks.mark_plan_step(task, name, "completed")
        db.commit()
        await persist_step(name, args, "pending" if result.get("pending") else "done", result.get("summary") or "", duration)
        yield {
            "type": "step",
            "step": {
                "index": step_index, "tool": name, "label": _tool_label(name),
                "status": "pending" if result.get("pending") else "done",
                "summary": (result.get("summary") or "")[:400],
                "duration_ms": duration,
            },
        }
        return

    async def emit_answer(text: str):
        for piece in _chunk_text(text):
            async for control in agent_tasks.control_events(db, task):
                yield control
            yield {"type": "delta", "text": piece}

    if _should_translate(question):
        text = (
            "## 翻译需要生成式模型\n\n"
            "翻译不是检索任务，PaperLens 不会用模板伪造译文。请在「设置 → AI 模型」中配置 DeepSeek API Key，"
            "然后在阅读器中选中文本使用右侧面板的「翻译」，或直接把需要翻译的段落粘贴到对话中。"
        )
        async for piece in emit_answer(text):
            yield piece
        yield {"type": "answer", "text": text}
        return

    if re.search(r"矩阵|冲突|演化|研究情报|趋势|机会|landscape|matrix|conflict|evolution|intelligenc|opportunit", question, re.I):
        if re.search(r"矩阵|matrix", question, re.I):
            section = "matrix"
        elif re.search(r"冲突|conflict", question, re.I):
            section = "conflicts"
        elif re.search(r"演化|evolution", question, re.I):
            section = "evolution"
        else:
            section = "landscape"
        async for event in run_tool("research_intelligence", {"question": question[:500], "section": section}):
            yield event
        summary = (last.get("value") or {}).get("summary") or ""
        combined = summary + "\n\n" + compose_local_answer(question, runner.citations, "explore", papers)
        async for piece in emit_answer(combined):
            yield piece
        yield {"type": "answer", "text": combined}
        return

    if _should_compare(question, papers):
        async for event in run_tool("compare_papers", {"paper_ids": [p.id for p in papers[:6]], "focus": question[:300]}):
            yield event
        answer = compose_local_answer(question, runner.citations, "multi_paper", papers)
        async for piece in emit_answer(answer):
            yield piece
        yield {"type": "answer", "text": answer}
        return

    if _should_gap(question):
        async for event in run_tool("analyze_research_gap", {"paper_ids": [p.id for p in papers[:8]]}):
            yield event
        citations = [c for c in runner.citations if c.get("chunk_id")]
        gap_text = ""
        if papers:
            gap_text, gap_citations = analysis.local_gap_analysis(db, papers[:8])
            for citation in gap_citations:
                if citation["chunk_id"] not in {c.get("chunk_id") for c in collected}:
                    collected.append(citation)
        combined = gap_text + "\n\n" + compose_local_answer(question, citations, "explore", papers)
        async for piece in emit_answer(combined):
            yield piece
        yield {"type": "answer", "text": combined}
        return

    if _should_report(question) and papers:
        async for event in run_tool("generate_report", {"topic": question[:300], "paper_ids": [p.id for p in papers[:6]]}):
            yield event
        report_text = (last.get("value") or {}).get("summary") or (analysis.LOCAL_BANNER + f"# 研究报告：{question[:120]}\n")
        async for piece in emit_answer(report_text):
            yield piece
        yield {"type": "answer", "text": report_text}
        return

    citations = rag_search(db, user.id, question, [p.id for p in papers] if papers else None, top_k=10)
    async for event in run_tool("retrieve_chunks", {"query": question, "paper_ids": [p.id for p in papers] if papers else None, "top_k": 8}):
        yield event

    if _should_figures(question):
        async for event in run_tool("extract_figures", {"paper_id": papers[0].id if len(papers) == 1 else None, "query": ""}):
            yield event

    if _should_summary(question) and len(papers) == 1:
        async for event in run_tool("summarize_paper", {"paper_id": papers[0].id, "mode": "abstract"}):
            yield event

    answer = compose_local_answer(question, citations, mode, papers)
    if _should_save(question) and citations:
        proposal = await runner.run(
            "save_knowledge",
            {
                "title": f"研究笔记：{question[:60]}",
                "content": answer[:3000],
                "kind": "insight",
                "paper_id": citations[0]["paper_id"],
                "page": citations[0]["page"],
                "tags": ["agent", "research-note"],
            },
        )
        if proposal.get("pending") and proposal.get("action"):
            actions.append(proposal["action"])
            yield {"type": "action", "action": proposal["action"]}
            answer += "\n\n---\n已生成待确认的保存操作，请在下方确认后写入知识库。"
        elif (proposal.get("data") or {}).get("duplicate_of"):
            answer += "\n\n---\n未保存：检测到相似知识，已阻止重复条目。"

    async for control in agent_tasks.control_events(db, task):
        yield control
    async for piece in emit_answer(answer):
        yield piece
    yield {"type": "answer", "text": answer}


async def confirm_action(db: Session, user: User, tool: str, args: dict) -> dict:
    """Execute a previously proposed write action after explicit user confirmation."""
    config = resolve_model_config(db, user)
    runner = ToolRunner(db, user, config, scope_ids=None, allow_writes=True)
    result = await runner.run(tool, args)
    return result