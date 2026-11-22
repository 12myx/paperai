"""P6 Agent task control: plans, state machine, self-check.

The planner is deterministic and does not pretend to be a model. It exposes the
steps and tools *before* execution so the user can inspect or adjust them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AgentRun, AgentStep, AgentTask, Paper, User, utcnow

logger = logging.getLogger("paperlens.agent_tasks")
from .llm import LLMClient, LLMError, ModelConfig
from .tools import TOOL_SPECS

ALLOWED_TOOLS = {spec["function"]["name"] for spec in TOOL_SPECS} | {"research_intelligence"}

COMPLEX_RE = re.compile(
    r"(研究计划|实验设计|文献综述|综述|开题|研究缺口|对比|比较|矩阵|冲突|演化|"
    r"研究情报|趋势|研究机会|报告|多篇|这些论文|全部论文|survey|literature review|"
    r"research plan|experiment design|compare|gap|matrix|conflict|evolution|landscape|opportunit)",
    re.I,
)


class TaskCancelled(Exception):
    pass


def is_complex(message: str, mode: str, paper_count: int = 0) -> bool:
    if mode in {"deep_read", "critical", "multi_paper"}:
        return True
    if paper_count >= 3 and COMPLEX_RE.search(message):
        return True
    return bool(COMPLEX_RE.search(message))


def _step(step_id: str, title: str, tool: str | None, depends: list[str], description: str) -> dict:
    return {
        "id": step_id,
        "title": title,
        "tool": tool,
        "depends_on": depends,
        "description": description,
        "status": "pending",
    }


def build_plan(goal: str, mode: str, papers: list[Paper]) -> list[dict]:
    count = len(papers)
    text = goal.lower()
    steps = [
        _step("s1", "确认研究范围与目标", None, [], f"资料库内 {count} 篇论文；明确要回答的问题与边界。"),
    ]

    def append(step_id: str, title: str, tool: str | None, depends: list[str], description: str) -> None:
        steps.append(_step(step_id, title, tool, depends, description))

    if re.search(r"翻译|translate", text) and "翻译" in goal:
        append("s2", "生成译文", "translate_content", ["s1"], "需要已配置生成式模型；不会用模板伪造译文。")
    elif count >= 2 and re.search(r"对比|比较|差异|区别|compare|versus", text):
        append("s2", "结构化对比论文", "compare_papers", ["s1"], "按方法、实验、结论与条件对比，返回原文证据。")
    elif re.search(r"缺口|空白|未来方向|gap|open problem", text):
        append("s2", "检索研究缺口", "analyze_research_gap", ["s1"], "区分作者明确局限与推断，返回证据。")
    elif re.search(r"报告|综述|survey|report|文献回顾", text):
        append("s2", "生成研究报告", "generate_report", ["s1"], "基于检索证据生成报告草稿，不添加未检索到的文献。")
    elif re.search(r"矩阵|冲突|演化|研究情报|趋势|机会|landscape|matrix|conflict|evolution|opportunit", text):
        section = "matrix" if re.search(r"矩阵|matrix", text) else "conflicts" if re.search(r"冲突|conflict", text) else "evolution" if re.search(r"演化|evolution", text) else "landscape"
        append("s2", "生成研究情报", "research_intelligence", ["s1"], f"调用资料库研究情报（section={section}），只分析当前范围。")
    elif re.search(r"总结|概括|摘要|贡献|summar", text) and count == 1:
        append("s2", "总结论文", "summarize_paper", ["s1"], "按章节抽取摘要、方法与结论。")
    else:
        append("s2", "检索原文证据", "retrieve_chunks", ["s1"], "检索与问题最相关的真实片段，并保留页码。")

    append("s3", "组织答案并标注证据", None, ["s2"], "只使用已检索证据；证据不足时明确说明。")
    append("s4", "执行证据自检", None, ["s3"], "检查引用覆盖、失败步骤与证据边界。")
    return steps


def create_task(
    db: Session,
    user: User,
    *,
    goal: str,
    mode: str,
    scope_type: str,
    scope_ids: list[str],
    conversation_id: str | None = None,
    plan: list[dict] | None = None,
    plan_source: str = "local",
    status: str = "queued",
    plan_confirmed: bool = False,
    rerun_of: str | None = None,
) -> AgentTask:
    task = AgentTask(
        user_id=user.id,
        conversation_id=conversation_id,
        goal=goal[:2000],
        mode=mode,
        scope_type=scope_type,
        scope_ids=scope_ids,
        status=status,
        plan=plan or [],
        plan_source=plan_source,
        plan_confirmed=plan_confirmed,
        provider="local",
        rerun_of=rerun_of,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


async def build_plan_with_model(
    goal: str,
    mode: str,
    papers: list[Paper],
    config: ModelConfig | None,
) -> tuple[list[dict], str]:
    """Ask the model for a bounded plan; fall back to the deterministic plan.

    The model only sees paper titles and the goal, never full text. Tool names
    are validated against the real tool belt, and the plan is capped at 5 steps.
    """
    fallback = build_plan(goal, mode, papers)
    if config is None:
        return fallback, "local"
    titles = "\n".join(f"- {paper.title} ({paper.year or 'n.d.'})" for paper in papers[:12]) or "（资料库为空）"
    prompt = (
        "只输出 JSON，不要 Markdown。为科研任务生成 2-5 个可执行步骤。格式："
        "{\"steps\":[{\"title\":\"\",\"tool\":\"retrieve_chunks\",\"description\":\"\","
        "\"depends_on\":[\"s1\"]}]}。"
        "工具只能从以下选择：" + ", ".join(sorted(ALLOWED_TOOLS)) + "。"
        "没有证据的任务不要声称已经完成；最多 5 步；不要编造论文、数据或引用。"
        "\n\n研究范围：\n" + titles + "\n\n任务：" + goal[:1500]
    )
    try:
        response = await LLMClient(config).complete(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=900
        )
        cleaned = (response.get("content") or "").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return fallback, "local"
        payload = json.loads(cleaned[start : end + 1])
        raw_steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            return fallback, "local"
        steps = [_step("s1", "确认研究范围与目标", None, [], f"资料库内 {len(papers)} 篇论文；明确问题与边界。")]
        for index, item in enumerate(raw_steps[:5], start=2):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()[:160]
            tool = item.get("tool")
            if not title or (tool and str(tool) not in ALLOWED_TOOLS):
                continue
            steps.append(
                _step(
                    f"s{index}",
                    title,
                    str(tool) if tool else None,
                    [],
                    str(item.get("description") or "")[:400],
                )
            )
        steps.append(_step(f"s{len(steps) + 1}", "组织答案并标注证据", None, [steps[-1]["id"]], "只使用已检索证据；不足时明确说明。"))
        steps.append(_step(f"s{len(steps) + 1}", "执行证据自检", None, [steps[-1]["id"]], "检查引用覆盖、失败步骤与证据边界。"))
        return steps, "model"
    except (LLMError, json.JSONDecodeError, ValueError):
        return fallback, "local"


def apply_plan_update(task: AgentTask, raw: list[dict]) -> list[dict]:
    if task.status not in {"queued", "paused"}:
        raise ValueError("当前任务状态不允许修改计划")
    if not raw or len(raw) > 8:
        raise ValueError("计划需要 1–8 个步骤")
    normalized: list[dict] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("计划步骤格式错误")
        title = str(item.get("title") or "").strip()[:160]
        if not title:
            raise ValueError("计划步骤标题不能为空")
        tool = item.get("tool")
        if tool in {"", None}:
            tool = None
        elif str(tool) not in ALLOWED_TOOLS:
            raise ValueError(f"不允许的工具：{tool}")
        else:
            tool = str(tool)
        step_id = str(item.get("id") or f"s{index + 1}")[:32]
        if step_id in ids:
            step_id = f"s{index + 1}"
        ids.add(step_id)
        depends = [str(dep) for dep in (item.get("depends_on") or []) if str(dep) in ids]
        normalized.append(
            {
                "id": step_id,
                "title": title,
                "tool": tool,
                "depends_on": depends,
                "description": str(item.get("description") or "")[:600],
                "status": "pending",
            }
        )
    task.plan = normalized
    task.updated_at = utcnow()
    return normalized


def mark_plan_step(task: AgentTask, tool: str | None, status: str, title_hint: str | None = None) -> None:
    plan = [dict(step) for step in (task.plan or [])]
    for step in plan:
        if step.get("status") in {"completed", "failed", "skipped"}:
            continue
        if (tool and step.get("tool") == tool) or (not tool and not step.get("tool") and title_hint and title_hint in str(step.get("title"))):
            step["status"] = status
            task.current_step = str(step.get("title"))[:240]
            break
    task.plan = plan
    completed = sum(1 for step in plan if step.get("status") in {"completed", "skipped"})
    task.progress = min(100, int(completed / max(len(plan), 1) * 100))
    task.updated_at = utcnow()


def complete_plan(task: AgentTask) -> None:
    plan = [dict(step) for step in (task.plan or [])]
    for step in plan:
        if step.get("status") not in {"failed", "skipped"}:
            step["status"] = "completed"
    task.plan = plan
    task.progress = 100
    task.current_step = "已完成"
    task.updated_at = utcnow()


def self_check(goal: str, answer: str, citations: list[dict], steps: list[AgentStep], plan: list[dict]) -> dict:
    keys = {citation.get("key") for citation in citations if citation.get("key")}
    used = set(re.findall(r"\[(C\d+)\]", answer or ""))
    missing_keys = sorted(used - keys)
    failed = [
        {"index": step.index, "tool": step.tool_name, "error": (step.output_summary or "")[:300]}
        for step in steps
        if step.status == "error"
    ]
    paper_ids = {citation.get("paper_id") for citation in citations if citation.get("paper_id")}
    issues: list[str] = []
    warnings: list[str] = []
    if not answer.strip():
        issues.append("没有生成答案")
    if not citations:
        issues.append("没有引用任何原文证据")
    if used and missing_keys:
        warnings.append("答案使用了未返回的引用编号：" + "、".join(missing_keys))
    if citations and not used and len(answer) > 120:
        warnings.append("答案没有使用 [C#] 引用编号，需人工核对证据覆盖")
    if re.search(r"冲突|矛盾|contradict|conflict", answer, re.I) and len(paper_ids) < 2:
        warnings.append("答案提到冲突/矛盾，但证据来自少于两篇论文")
    if failed:
        warnings.append(f"{len(failed)} 个工具步骤失败，结论可能不完整")
    if len(plan) and all(step.get("status") == "pending" for step in plan):
        warnings.append("计划步骤未执行")

    score = 100
    score -= 30 if not answer.strip() else 0
    score -= 35 if not citations else 0
    score -= 10 if missing_keys else 0
    score -= 8 * len(failed)
    score -= 5 if citations and not used and len(answer) > 120 else 0
    score = max(0, min(100, score))
    if issues:
        status = "fail" if score < 60 else "warning"
    elif warnings:
        status = "warning"
    else:
        status = "pass"
    summary_parts = [
        "目标完成" if answer.strip() else "目标未完成",
        f"引用 {len(citations)} 条 / 涉及 {len(paper_ids)} 篇论文",
        f"失败步骤 {len(failed)} 个",
    ]
    if warnings:
        summary_parts.append("；".join(warnings))
    return {
        "status": status,
        "score": score,
        "goal_completed": bool(answer.strip()),
        "citation_count": len(citations),
        "paper_count": len(paper_ids),
        "missing_citation_keys": missing_keys,
        "failed_steps": failed,
        "issues": issues,
        "warnings": warnings,
        "summary": " · ".join(summary_parts),
    }


async def control_events(db: Session, task: AgentTask) -> AsyncIterator[dict]:
    """Cooperative pause/resume/cancel checkpoint."""
    db.refresh(task)
    if task.status == "cancelled":
        raise TaskCancelled()
    if task.status != "paused":
        return
    yield {"type": "paused", "task_id": task.id, "message": "任务已暂停；继续后从当前检查点恢复。"}
    while True:
        await asyncio.sleep(0.25)
        db.refresh(task)
        if task.status == "cancelled":
            raise TaskCancelled()
        if task.status == "running":
            yield {"type": "resumed", "task_id": task.id, "message": "任务已继续。"}
            return


def recover_interrupted_tasks() -> int:
    """Mark tasks left running/paused by a previous process as interrupted.

    Task execution is bound to an HTTP stream. After a process restart there is
    no stream to resume, so leaving these rows as running would make the task
    center lie forever. Queued tasks are intentionally left untouched because
    the user can still execute them explicitly.
    """
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(AgentTask).where(AgentTask.status.in_(["running", "paused"]))
            ).scalars().all()
        )
        for task in rows:
            task.status = "failed"
            task.error = "服务重启导致任务执行中断，请重新执行。"
            task.finished_at = utcnow()
            task.updated_at = utcnow()
            if task.run_id:
                run = db.get(AgentRun, task.run_id)
                if run is not None and run.status in {"running", "paused"}:
                    run.status = "failed"
                    run.error = "服务重启导致任务执行中断"
                    run.finished_at = utcnow()
        if rows:
            db.commit()
            logger.warning("Recovered %s interrupted agent task(s)", len(rows))
        return len(rows)