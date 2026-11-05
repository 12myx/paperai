"""P8 academic artifacts + deterministic quality checker.

Local mode is an extractive composer: every substantive sentence comes from a
paper facet with a real [C#] citation. Planning/timeline text is explicitly
labelled as a proposal, not a literature fact. No external references are
invented.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AcademicArtifact, ArtifactQualityReport, Chunk, ExportRecord, Paper, User
from . import analysis
from .export import build_export
from .evidence import verify_quote
from .intelligence import IntelligenceError, resolve_scope
from .multipaper import _facet_citations, ensure_facets
from .storage import safe_filename, storage

KINDS = {
    "literature_review": {"label": "文献综述", "description": "资料库范围内的研究背景、方法版图、发现与缺口。"},
    "reading_report": {"label": "阅读报告", "description": "逐篇整理问题、方法、实验、发现与局限。"},
    "comparison_report": {"label": "对比报告", "description": "多篇论文的方法、数据、指标与结论对照。"},
    "direction_analysis": {"label": "方向分析", "description": "从真实问题与局限中整理研究方向。"},
    "proposal_draft": {"label": "开题初稿", "description": "背景、问题、方法、实验与风险的初稿。"},
    "research_plan": {"label": "研究计划", "description": "阶段、里程碑与交付物建议；时间表为建议。"},
    "experiment_design": {"label": "实验设计", "description": "数据集、指标、基线、消融与风险。"},
    "ppt_outline": {"label": "PPT 大纲", "description": "组会/答辩用的 10 页汇报大纲。"},
}

REQUIRED = {
    "literature_review": ["范围与证据声明", "摘要", "研究背景与问题", "方法版图", "主要发现", "局限与研究缺口", "资料库内参考文献"],
    "reading_report": ["范围与证据声明", "阅读报告", "证据表说明"],
    "comparison_report": ["范围与证据声明", "对比总览", "共同点", "差异与条件", "局限", "结论边界"],
    "direction_analysis": ["范围与证据声明", "研究问题", "方法现状", "局限与缺口", "候选方向", "验证建议"],
    "proposal_draft": ["范围与证据声明", "研究背景", "研究问题", "方法与路线", "实验设计", "预期贡献", "风险与边界"],
    "research_plan": ["范围与证据声明", "目标", "阶段安排", "里程碑与交付物", "风险与依赖"],
    "experiment_design": ["范围与证据声明", "数据与指标", "基线与变量", "消融与对照", "评估与统计", "风险与边界"],
    "ppt_outline": ["范围与证据声明", "Slide 1", "Slide 2", "Slide 3", "Slide 4", "Slide 5", "Slide 6", "Slide 7", "Slide 8", "Slide 9", "Slide 10"],
}

STRONG_CLAIM = re.compile(
    r"(表明|证明|显著|优于|低于|因果|首次|必然|显然|clearly|proves?|demonstrates?|significantly|superior|outperforms?)",
    re.I,
)


def _short(text: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _cite(citation: dict | None) -> str:
    return f" [{citation['key']}]" if citation and citation.get("key") else ""


def _cell(facet, field: str) -> dict:
    return ((facet.fields or {}).get(field) or {}) if facet else {}


def _item(facet, paper: Paper, field: str, index: dict) -> dict:
    cell = _cell(facet, field)
    citation = index.get((paper.id, cell.get("chunk_id")))
    return {
        "text": cell.get("text") or "未提及",
        "citation": citation,
        "page": cell.get("page"),
        "verified": cell.get("verified"),
    }


def _scope_statement(scope: dict) -> str:
    years = f"{scope.get('year_min')}–{scope.get('year_max')}" if scope.get("year_min") else "年份未知"
    return (
        f"本成果仅基于资料库内 {scope['paper_count']} 篇论文（{years}），不代表全球文献综述，"
        "也未引入外部文献。所有带 [C#] 的判断均可回到原文；计划、时间表与实验建议属于待验证方案，不是论文事实。"
    )


def _evidence_table(citations: list[dict]) -> list[dict]:
    return [
        {
            "key": c.get("key"),
            "paper_id": c.get("paper_id"),
            "paper_title": c.get("paper_title"),
            "page": c.get("page"),
            "section": c.get("section"),
            "quote": c.get("quote"),
            "verified": bool(c.get("verified")),
        }
        for c in citations
    ]


def _used_citations(content: str, citations: list[dict]) -> list[dict]:
    used = set(re.findall(r"\[(C\d+)\]", content))
    return [c for c in citations if c.get("key") in used]


def build_content(kind: str, papers: list[Paper], facets: list, citations: list[dict], scope: dict) -> tuple[str, list[dict]]:
    index = {(c["paper_id"], c.get("chunk_id")): c for c in citations if c.get("chunk_id")}
    by_paper = {paper.id: paper for paper in papers}
    rows = []
    for facet in facets:
        paper = by_paper.get(facet.paper_id)
        if paper is None:
            continue
        item = {field: _item(facet, paper, field, index) for field in ("research_question", "method", "dataset", "metrics", "findings", "limitations")}
        rows.append((paper, item))

    lines = [f"# {kind_title(kind, papers)}", "", "## 范围与证据声明", "", _scope_statement(scope), ""]

    if kind == "literature_review":
        lines += ["## 摘要", ""]
        for paper, item in rows[:4]:
            lines.append(f"- 《{paper.title}》（{paper.year or '年份未知'}）研究「{_short(item['research_question']['text'], 80)}」，采用 {item['method']['text']}{_cite(item['method']['citation'])}。")
        lines += ["", "## 研究背景与问题", ""]
        for paper, item in rows:
            lines.append(f"- **{paper.title}**：{item['research_question']['text']}{_cite(item['research_question']['citation'])}")
        lines += ["", "## 方法版图", ""]
        for paper, item in rows:
            lines.append(f"- {item['method']['text']}{_cite(item['method']['citation'])}")
        lines += ["", "## 主要发现", ""]
        for paper, item in rows:
            lines.append(f"- 《{paper.title}》：{item['findings']['text']}{_cite(item['findings']['citation'])}")
        lines += ["", "## 局限与研究缺口", ""]
        for paper, item in rows:
            lines.append(f"- {item['limitations']['text']}{_cite(item['limitations']['citation'])}")
        lines += ["", "## 资料库内参考文献", ""]
        for paper in papers:
            lines.append(f"- {paper.title}. {paper.year or 'n.d.'}. 资料库内论文（id={paper.id}）。")

    elif kind == "reading_report":
        lines += ["## 阅读报告", ""]
        for paper, item in rows:
            lines += [f"### {paper.title}（{paper.year or '年份未知'}）", ""]
            for field, label in (("research_question", "研究问题"), ("method", "方法"), ("dataset", "数据"), ("metrics", "指标"), ("findings", "主要发现"), ("limitations", "局限")):
                lines.append(f"- **{label}**：{item[field]['text']}{_cite(item[field]['citation'])}（p.{item[field]['page'] or '?'}）")
            lines.append("")

    elif kind == "comparison_report":
        lines += ["## 对比总览", "", "| 论文 | 研究问题 | 方法 | 数据/指标 | 主要发现 |", "| --- | --- | --- | --- | --- |"]
        for paper, item in rows:
            lines.append(f"| {paper.title} | {_short(item['research_question']['text'], 55)} | {_short(item['method']['text'], 55)} | {_short(item['dataset']['text'], 40)} / {_short(item['metrics']['text'], 40)} | {_short(item['findings']['text'], 70)} |")
        lines += ["", "## 共同点", ""]
        lines.append("以上论文都提供了可定位的原文片段；共同点只按文本并列，不推断未写出的因果关系。")
        lines += ["", "## 差异与条件", ""]
        for paper, item in rows:
            lines.append(f"- 《{paper.title}》的条件：{item['dataset']['text']}；{item['metrics']['text']}{_cite(item['metrics']['citation'])}")
        lines += ["", "## 局限", ""]
        for paper, item in rows:
            lines.append(f"- {item['limitations']['text']}{_cite(item['limitations']['citation'])}")
        lines += ["", "## 结论边界", "", "条件不同的结果不能直接判定为观点冲突；需要人工核对实验设置。"] 

    elif kind == "direction_analysis":
        lines += ["## 研究问题", ""]
        for paper, item in rows:
            lines.append(f"- {item['research_question']['text']}{_cite(item['research_question']['citation'])}")
        lines += ["", "## 方法现状", ""]
        for paper, item in rows:
            lines.append(f"- {item['method']['text']}{_cite(item['method']['citation'])}")
        lines += ["", "## 局限与缺口", ""]
        for paper, item in rows:
            lines.append(f"- {item['limitations']['text']}{_cite(item['limitations']['citation'])}")
        lines += ["", "## 候选方向", ""]
        for paper, item in rows[:4]:
            lines.append(f"- 围绕「{_short(item['limitations']['text'], 80)}」设计对照实验；依据：{_cite(item['limitations']['citation'])}")
        lines += ["", "## 验证建议", "", "- 先复现原文基线，再做单变量消融；不要把本节的候选方向当作已验证结论。"]

    elif kind == "proposal_draft":
        main = rows[0] if rows else (None, None)
        lines += ["## 研究背景", ""]
        for paper, item in rows:
            lines.append(f"- 《{paper.title}》指出：{item['research_question']['text']}{_cite(item['research_question']['citation'])}")
        lines += ["", "## 研究问题", ""]
        for paper, item in rows:
            lines.append(f"- {item['research_question']['text']}{_cite(item['research_question']['citation'])}")
        lines += ["", "## 方法与路线", ""]
        for paper, item in rows:
            lines.append(f"- 已有路线：{item['method']['text']}{_cite(item['method']['citation'])}")
        lines.append("- 本开题建议：在原文基线上增加针对局限的对照实验；该建议需要导师与文献复核。")
        lines += ["", "## 实验设计", ""]
        for paper, item in rows:
            lines.append(f"- 数据/指标：{item['dataset']['text']}；{item['metrics']['text']}{_cite(item['metrics']['citation'])}")
        lines += ["", "## 预期贡献", "", "- 预期贡献是待验证假设，不是已实现结果；需通过实验与统计检验确认。"]
        lines += ["", "## 风险与边界", ""]
        for paper, item in rows:
            lines.append(f"- 原文局限：{item['limitations']['text']}{_cite(item['limitations']['citation'])}")

    elif kind == "research_plan":
        lines += ["## 目标", "", "在资料库证据基础上完成一个可复现的研究闭环；时间安排是建议，不是承诺。", "", "## 阶段安排", ""]
        phases = [
            ("第 1–2 周", "复现与基线", "复现原文方法、数据与指标，记录环境与随机种子。"),
            ("第 3–4 周", "问题定位", "围绕原文局限设计最小对照实验，确认变量。"),
            ("第 5–6 周", "主实验", "扩展到多数据集/多指标，报告均值、方差与显著性。"),
            ("第 7–8 周", "写作与质检", "整理证据表、失败案例与限制，完成初稿与复现清单。"),
        ]
        for phase, title, detail in phases:
            lines.append(f"- **{phase} · {title}**：{detail}")
        lines += ["", "## 里程碑与交付物", "", "- M1 复现记录与基线表", "- M2 实验设计 v1", "- M3 主结果与消融", "- M4 初稿 + 证据表 + 质检报告"]
        lines += ["", "## 风险与依赖", "- 数据/算力不足、原文实现缺失、指标不可比；每一项都需要在开题前确认。"]
        for paper, item in rows:
            lines.append(f"- 《{paper.title}》局限：{item['limitations']['text']}{_cite(item['limitations']['citation'])}")

    elif kind == "experiment_design":
        lines += ["## 数据与指标", ""]
        for paper, item in rows:
            lines.append(f"- 《{paper.title}》：数据 {item['dataset']['text']}；指标 {item['metrics']['text']}{_cite(item['metrics']['citation'])}")
        lines += ["", "## 基线与变量", "", "- 基线：优先复用原文报告的方法与设置；缺失时标记“未提及”，不得补造。"]
        for paper, item in rows:
            lines.append(f"- 候选基线：{item['method']['text']}{_cite(item['method']['citation'])}")
        lines += ["", "## 消融与对照", "", "- 单变量消融：只改变与原文局限相关的模块/数据条件。", "- 对照：相同数据、相同指标、相同预算；报告失败案例。"]
        lines += ["", "## 评估与统计", "", "- 报告均值、方差、置信区间与显著性；不要只报告最好结果。", "- 复现实验至少 3 个随机种子。"]
        lines += ["", "## 风险与边界", ""]
        for paper, item in rows:
            lines.append(f"- {item['limitations']['text']}{_cite(item['limitations']['citation'])}")

    elif kind == "ppt_outline":
        slides = [
            ("Slide 1", "标题与范围", f"资料库内 {len(papers)} 篇论文；明确不代表全球综述。"),
            ("Slide 2", "问题", "研究问题与动机；引用原文。"),
            ("Slide 3", "方法", "方法路线与关键设计；引用原文。"),
            ("Slide 4", "数据与指标", "数据集、指标与实验条件。"),
            ("Slide 5", "主要结果", "只展示原文报告的结果；标注页码。"),
            ("Slide 6", "对比", "条件可比性；不可比时只列差异。"),
            ("Slide 7", "局限", "作者明确局限与未验证部分。"),
            ("Slide 8", "研究机会", "候选方向，标注为建议。"),
            ("Slide 9", "计划", "阶段、里程碑与风险。"),
            ("Slide 10", "证据与复现", "证据表、范围声明、复现清单。"),
        ]
        for slide, title, desc in slides:
            lines += [f"## {slide}：{title}", "", f"- {desc}"]
            if rows:
                paper, item = rows[(int(slide.split()[1]) - 1) % len(rows)]
                lines.append(f"- 证据：{_short(item['findings']['text'], 90)}{_cite(item['findings']['citation'])}（{paper.title}）")
            lines.append("")

    lines += ["", "## 证据表说明", "", "完整证据表由系统单独保存并在导出文件中附上；[C#] 编号对应证据表的 key。"]
    content = "\n".join(lines).strip() + "\n"
    used = _used_citations(content, citations)
    return content, used


def kind_title(kind: str, papers: list[Paper]) -> str:
    label = KINDS.get(kind, {}).get("label", "学术成果")
    if len(papers) == 1:
        return f"{label}：{papers[0].title}"
    return f"{label}：资料库 {len(papers)} 篇论文"


def check_artifact(db: Session, artifact: AcademicArtifact) -> dict:
    content = artifact.content or ""
    citations = artifact.citations or []
    issues: list[dict] = []
    used = set(re.findall(r"\[(C\d+)\]", content))
    keys = {c.get("key") for c in citations}
    missing = sorted(used - keys)
    for key in missing:
        issues.append({"code": "missing_citation", "severity": "error", "message": f"引用 {key} 不在证据表中", "location": key})
    if not citations:
        issues.append({"code": "no_evidence", "severity": "error", "message": "成果没有任何证据", "location": "evidence"})
    if not used and content:
        issues.append({"code": "no_inline_citations", "severity": "warning", "message": "正文没有 [C#] 引用", "location": "body"})

    for citation in citations:
        chunk = db.get(Chunk, citation.get("chunk_id")) if citation.get("chunk_id") else None
        if chunk is None:
            issues.append({"code": "quote_chunk_missing", "severity": "error", "message": f"引用 {citation.get('key')} 的原文切片不存在", "location": citation.get("key")})
            continue
        ok, note = verify_quote(chunk.text, citation.get("quote") or "")
        if not ok:
            issues.append({"code": "quote_mismatch", "severity": "error", "message": f"引用 {citation.get('key')} 未在原文中匹配：{note}", "location": citation.get("key")})

    headings = set(re.findall(r"^##\s+(.+)$", content, re.M))
    for section in REQUIRED.get(artifact.kind, []):
        if not any(section in heading for heading in headings):
            issues.append({"code": "missing_section", "severity": "error", "message": f"缺少章节：{section}", "location": section})

    if "仅基于资料库" not in content or "不代表全球" not in content:
        issues.append({"code": "scope_missing", "severity": "error", "message": "缺少范围/证据声明", "location": "scope"})
    if len(artifact.evidence_table or []) == 0:
        issues.append({"code": "evidence_table_empty", "severity": "error", "message": "证据表为空", "location": "evidence_table"})
    if len(content.strip()) < 900:
        issues.append({"code": "too_short", "severity": "warning", "message": "成果篇幅过短，可能遗漏关键部分", "location": "format"})

    sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s*", content) if len(s.strip()) >= 30]
    seen: dict[str, int] = {}
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).casefold()
        seen[normalized] = seen.get(normalized, 0) + 1
    for sentence, count in seen.items():
        if count > 1:
            issues.append({"code": "duplicate_sentence", "severity": "warning", "message": f"重复句子 {count} 次：{_short(sentence, 60)}", "location": "body"})

    for sentence in sentences:
        if STRONG_CLAIM.search(sentence) and not re.search(r"\[C\d+\]", sentence) and not sentence.startswith("#"):
            issues.append({"code": "unsupported_claim", "severity": "warning", "message": f"强断言缺少引用：{_short(sentence, 80)}", "location": "body"})
            break

    if len(artifact.paper_ids or []) < 3:
        issues.append({"code": "small_scope", "severity": "warning", "message": f"仅覆盖 {len(artifact.paper_ids or [])} 篇论文，不能代表领域综述", "location": "scope"})

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    score = max(0, 100 - errors * 20 - warnings * 4)
    status = "fail" if errors else "warning" if warnings else "pass"
    summary = f"{len(citations)} 条证据 · 引用 {len(used)} 个 · 错误 {errors} · 警告 {warnings}"
    return {
        "status": status,
        "score": score,
        "issues": issues,
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def generate_artifact(
    db: Session,
    user: User,
    *,
    kind: str,
    scope_type: str,
    scope_id: str | None,
    paper_ids: list[str] | None,
    title: str | None,
    config,
) -> tuple[AcademicArtifact, ArtifactQualityReport]:
    if kind not in KINDS:
        raise ValueError("未知成果类型")
    try:
        papers, scope = resolve_scope(db, user, scope_type, scope_id, paper_ids)
    except IntelligenceError as exc:
        raise ValueError(str(exc)) from exc
    facets = await ensure_facets(db, user, papers, config, force=False)
    citations, _context = _facet_citations(db, papers, facets)
    content, used = build_content(kind, papers, facets, citations, scope)
    artifact = AcademicArtifact(
        user_id=user.id,
        kind=kind,
        title=(title or kind_title(kind, papers))[:390],
        scope_type=scope_type,
        scope_ids=list(paper_ids or ([scope_id] if scope_id else [])),
        paper_ids=[paper.id for paper in papers],
        content=content,
        citations=used,
        evidence_table=_evidence_table(used),
        scope_statement=_scope_statement(scope),
        local=True,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    check = check_artifact(db, artifact)
    report = ArtifactQualityReport(
        user_id=user.id,
        artifact_id=artifact.id,
        status=check["status"],
        score=check["score"],
        issues=check["issues"],
        summary=check["summary"],
    )
    db.add(report)
    artifact.quality_score = check["score"]
    artifact.quality_status = check["status"]
    db.commit()
    db.refresh(report)
    db.refresh(artifact)
    return artifact, report


def latest_report(db: Session, user: User, artifact_id: str) -> ArtifactQualityReport | None:
    return db.execute(
        select(ArtifactQualityReport)
        .where(ArtifactQualityReport.user_id == user.id, ArtifactQualityReport.artifact_id == artifact_id)
        .order_by(ArtifactQualityReport.checked_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def export_artifact(db: Session, user: User, artifact: AcademicArtifact, fmt: str) -> ExportRecord:
    fmt = fmt.lower()
    if fmt not in {"md", "pdf", "docx"}:
        raise ValueError("只支持 md/pdf/docx")
    evidence = ["", "## 证据表", "", "| key | 论文 | 页码 | 原文 | 核验 |", "| --- | --- | --- | --- | --- |"]
    for row in artifact.evidence_table or []:
        evidence.append(f"| {row.get('key')} | {str(row.get('paper_title') or '').replace('|', '/')} | {row.get('page') or ''} | {str(row.get('quote') or '').replace('|', '/')[:180]} | {'是' if row.get('verified') else '否'} |")
    content = artifact.content + "\n" + "\n".join(evidence)
    data, ext = build_export(fmt, artifact.title, content, meta={"kind": artifact.kind, "scope": artifact.scope_statement})
    filename = f"{safe_filename(artifact.title, 'paperlens-artifact')}-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"
    relative = storage.save_export(user.id, filename, data)
    record = ExportRecord(
        user_id=user.id, kind=f"artifact-{artifact.kind}", title=artifact.title[:290],
        format=ext, filename=filename, path=relative, size_bytes=len(data),
        meta={"artifact_id": artifact.id},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record