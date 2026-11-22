"""Grounded analysis helpers.

Every function here works with *real* retrieved text. When a model is
configured the analysis is generative; otherwise it degrades to an explicit,
clearly labelled extractive mode built from the same evidence.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Paper
from .llm import LLMClient, LLMError, ModelConfig, system_prompt
from .rag import format_citations, search

LOCAL_BANNER = "> 本地抽取 · 未配置生成式模型；以下内容仅来自原文，不是生成或推断。\n\n"

SUMMARY_MODES = {
    "one_line": "用一句话（不超过 80 字）概括这篇论文的核心贡献",
    "abstract": "生成 150-250 字的学术摘要，覆盖问题、方法、结果与结论",
    "section": "按章节结构总结全文，每个章节 2-3 句",
    "full": "生成完整的中文学术综述式总结，分层组织：研究问题、方法、实验、结论、局限",
    "plain": "用通俗易懂的语言解释这篇论文，面向非本领域的本科读者，避免术语堆砌",
    "academic": "用严谨的学术语言总结，保留关键术语、指标与实验设置",
    "method": "提炼研究方法：技术路线、关键模块、训练/推理流程与实现细节",
    "experiment": "提炼实验设置与结果：数据集、基线、指标、主要数值结论与消融实验",
    "innovation": "区分（a）作者明确声称的创新点、（b）可由内容支撑的贡献、（c）尚需文献验证的创新性判断",
    "limitation": "分析论文自身的局限性：方法假设、实验覆盖、数据偏差、泛化风险",
    "future": "提炼未来研究方向，并标注哪些来自作者、哪些来自你的推断",
}

SUMMARY_LABELS = {
    "one_line": "一句话总结", "abstract": "摘要总结", "section": "章节总结",
    "full": "全文总结", "plain": "通俗解读", "academic": "学术总结",
    "method": "研究方法", "experiment": "实验结果", "innovation": "创新点",
    "limitation": "研究局限", "future": "未来方向",
}


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s+", text.replace("\n", " "))
    return [p.strip() for p in parts if len(p.strip()) >= 24]


def pick_sentences(text: str, query: str, limit: int = 3) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return [text[:300]]
    terms = {t for t in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2}", (query or "").lower())}
    scored = []
    for index, sentence in enumerate(sentences):
        lowered = sentence.lower()
        overlap = sum(1 for term in terms if term in lowered)
        scored.append((overlap + (len(sentence) / 400.0) - index * 0.01, index, sentence))
    scored.sort(reverse=True)
    chosen = sorted(scored[:limit], key=lambda item: item[1])
    return [item[2] for item in chosen]


def paper_context(db: Session, paper: Paper, max_chars: int = 12000) -> tuple[str, list[dict]]:
    chunks = db.execute(
        select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index).limit(40)
    ).scalars().all()
    citations = []
    blocks = []
    used = 0
    for position, chunk in enumerate(chunks, start=1):
        if used > max_chars:
            break
        key = f"C{position}"
        blocks.append(f"[{key}] 第 {chunk.page_start} 页 · {chunk.section_title}\n{chunk.text[:2200]}")
        citations.append(
            {
                "key": key,
                "chunk_id": chunk.id,
                "paper_id": paper.id,
                "paper_title": paper.title,
                "paper_year": paper.year,
                "section": chunk.section_title,
                "page": chunk.page_start,
                "page_end": chunk.page_end,
                "quote": chunk.text[:1400],
                "score": 1.0,
                "kind": chunk.kind,
                "tags": list(chunk.tags or []),
            }
        )
        used += len(chunk.text)
    header = (
        f"论文标题：{paper.title}\n"
        f"作者：{paper.authors or '未知'}\n年份：{paper.year or '未知'}\n"
        f"摘要：{(paper.abstract or '无')[:1200]}\n"
    )
    return header + "\n\n".join(blocks), citations


def extractive_summary(db: Session, paper: Paper, mode: str) -> tuple[str, list[dict]]:
    chunks = db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
    if not chunks:
        return "该论文尚未成功解析出文本。", []

    def by_tags(*tags: str) -> list[Chunk]:
        matched = [c for c in chunks if any(tag in (c.tags or []) for tag in tags)]
        return matched or chunks

    citations: list[dict] = []

    def cite(chunk: Chunk, quote: str) -> str:
        key = f"C{len(citations) + 1}"
        citations.append(
            {
                "key": key,
                "chunk_id": chunk.id,
                "paper_id": paper.id,
                "paper_title": paper.title,
                "paper_year": paper.year,
                "section": chunk.section_title,
                "page": chunk.page_start,
                "page_end": chunk.page_end,
                "quote": quote[:1400],
                "score": 1.0,
                "kind": chunk.kind,
                "tags": list(chunk.tags or []),
            }
        )
        return f"[{key}]"

    sections: list[tuple[str, list[Chunk]]] = [
        ("研究问题与背景", by_tags("abstract", "introduction")[:2]),
        ("方法与技术路线", by_tags("method")[:3]),
        ("实验与结果", by_tags("experiment", "result")[:3]),
        ("结论与局限", by_tags("conclusion", "limitation", "discussion", "future-work")[:2]),
    ]
    if mode == "one_line":
        first = chunks[0]
        sentence = " ".join(pick_sentences(paper.abstract or first.text, paper.title, 1))[:160]
        return f"{sentence} {cite(first, sentence)}", citations

    if mode in {"method", "experiment"}:
        sections = [("方法与技术路线", by_tags("method")[:4])] if mode == "method" else [("实验与结果", by_tags("experiment", "result")[:4])]

    if mode in {"innovation", "limitation", "future"}:
        mapping = {
            "innovation": ("创新点相关原文", by_tags("abstract", "conclusion")[:3]),
            "limitation": ("局限相关原文", by_tags("limitation", "discussion", "conclusion")[:3]),
            "future": ("未来方向相关原文", by_tags("future-work", "conclusion", "discussion")[:3]),
        }
        title, pool = mapping[mode]
        lines = [LOCAL_BANNER, f"## {SUMMARY_LABELS[mode]}（原文证据）\n"]
        for chunk in pool:
            for sentence in pick_sentences(chunk.text, chunk.section_title, 2):
                lines.append(f"- {sentence} {cite(chunk, sentence)}")
        lines.append("\n> 以上为原文摘录，不构成对论文创新性或局限性的独立学术判断。")
        return "\n".join(lines), citations

    lines = [LOCAL_BANNER, f"## {SUMMARY_LABELS.get(mode, '论文总结')}\n"]
    if paper.abstract:
        lines.append(f"**摘要**：{paper.abstract[:900]}\n")
    for title, pool in sections:
        if not pool:
            continue
        lines.append(f"### {title}")
        for chunk in pool:
            for sentence in pick_sentences(chunk.text, title, 1):
                lines.append(f"- {sentence} {cite(chunk, sentence)}")
        lines.append("")
    lines.append("\n> 本地模式：仅列章节原文要点。")
    return "\n".join(lines), citations


async def generative_summary(db: Session, user, config: ModelConfig | None, paper: Paper, mode: str) -> tuple[str, list[dict], bool]:
    if config is None:
        text, citations = extractive_summary(db, paper, mode)
        return text, citations, True
    context, citations = paper_context(db, paper)
    instruction = SUMMARY_MODES.get(mode, SUMMARY_MODES["abstract"])
    messages = [
        {"role": "system", "content": system_prompt("deep_read")},
        {
            "role": "user",
            "content": f"任务：{instruction}\n\n论文原文（带引用编号）：\n{context}\n\n"
            "请只使用上述原文作答，引用使用 [C#] 标记。",
        },
    ]
    client = LLMClient(config)
    response = await client.complete(messages, temperature=0.2)
    return response["content"], citations, False


async def translate_text(config: ModelConfig | None, text: str, target: str, style: str = "academic") -> str:
    if config is None:
        raise LLMError("翻译需要生成式模型。请在「设置 → AI 模型」中配置 DeepSeek API Key。")
    if len(text) > 12000:
        text = text[:12000]
    messages = [
        {"role": "system", "content": "你是学术翻译专家。忠实翻译，保留术语、公式与引用标记，不添加解释。"},
        {
            "role": "user",
            "content": f"目标语言：{target}\n风格：{style}（学术论文）\n\n请翻译以下内容，仅输出译文：\n\n{text}",
        },
    ]
    response = await LLMClient(config).complete(messages, temperature=0.1)
    return response["content"].strip()


COMPARE_DIMENSIONS = [
    ("研究方法", ("method",), ("研究方法", "方法")),
    ("实验设计", ("experiment", "result"), ("实验设计", "实验设置", "实验")),
    ("创新点", ("innovation", "contribution", "conclusion", "abstract"), ("创新点", "创新")),
    ("局限性", ("limitation", "conclusion", "discussion"), ("局限性", "局限")),
    ("研究结论", ("conclusion", "abstract"), ("研究结论", "主要结论", "结论")),
    ("可复现性", ("method", "experiment", "reproducibility"), ("可复现性", "复现")),
]


def _compare_aspects(focus: str) -> list[tuple[str, tuple[str, ...]]]:
    value = focus or ""
    selected = [(label, tags) for label, tags, aliases in COMPARE_DIMENSIONS if any(alias in value for alias in aliases)]
    if selected:
        return selected
    custom = (focus or "").strip()
    if custom:
        return [(custom[:18], ())]
    return [("研究问题", ("abstract", "introduction")), ("研究方法", ("method",)), ("实验设计", ("experiment", "result")), ("研究结论", ("conclusion",))]


def local_compare(db: Session, papers: list[Paper], focus: str = "") -> tuple[str, list[dict]]:
    citations: list[dict] = []
    rows = []
    aspects = _compare_aspects(focus)
    for paper in papers:
        chunks = db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
        cells = []
        for label, tags in aspects:
            pool = [c for c in chunks if any(t in (c.tags or []) for t in tags)] or chunks
            if not pool:
                cells.append("—")
                continue
            chunk = pool[0]
            sentence = pick_sentences(chunk.text, focus or label, 1)[0]
            citations.append(
                {
                    "key": f"C{len(citations) + 1}",
                    "chunk_id": chunk.id,
                    "paper_id": paper.id,
                    "paper_title": paper.title,
                    "paper_year": paper.year,
                    "section": chunk.section_title,
                    "page": chunk.page_start,
                    "page_end": chunk.page_end,
                    "quote": sentence[:1400],
                    "score": 1.0,
                    "kind": chunk.kind,
                    "tags": list(chunk.tags or []),
                }
            )
            cells.append(f"{sentence[:180]} [C{len(citations)}]")
        rows.append((paper, cells))

    lines = [LOCAL_BANNER, "## 多论文对比（证据矩阵）\n"]
    header = "| 论文 | " + " | ".join(label for label, _ in aspects) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(aspects) + 1))
    for paper, cells in rows:
        title = paper.title.replace("|", "/")[:60]
        lines.append(f"| {title} | " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    lines.append("\n### 可复核的差异")
    for index, (paper, cells) in enumerate(rows):
        detail = next((cell for cell in cells if cell and cell != "—"), cells[0] if cells else "—")
        lines.append(f"- **{paper.title[:80]}**：{aspects[0][0]} — {detail[:220]}")
    lines.append("\n> 本地模式仅罗列各论文对应章节的原文要点；跨论文的因果、优劣与共识判断需要生成式模型。")
    return "\n".join(lines), citations


async def generative_compare(db: Session, config: ModelConfig | None, papers: list[Paper], focus: str) -> tuple[str, list[dict], bool]:
    if config is None:
        text, citations = local_compare(db, papers, focus)
        return text, citations, True
    blocks, citations = [], []
    cursor = 0
    for paper in papers:
        context, cites = paper_context(db, paper, max_chars=5000)
        blocks.append(f"### 论文 A{cursor + 1}: {paper.title}（{paper.year or 'n.d.'}）\n{context}")
        for cite in cites:
            cite["key"] = f"C{len(citations) + 1}"
            citations.append(cite)
        cursor += 1
    instruction = focus.strip() or "研究问题、方法、实验设计、主要结论、创新点、局限"
    messages = [
        {"role": "system", "content": system_prompt("multi_paper")},
        {
            "role": "user",
            "content": f"请对以下 {len(papers)} 篇论文做严谨对比。对比维度：{instruction}。\n"
            "输出结构：1) 共同点 2) 关键差异 3) 技术路线差异 4) 实验条件差异 5) 各自优势与不足 6) 对后续研究的启发。"
            "每个判断必须带 [C#] 引用；无证据时明确说明。\n\n" + "\n\n".join(blocks),
        },
    ]
    response = await LLMClient(config).complete(messages, temperature=0.25)
    return response["content"], citations, False


def local_gap_analysis(db: Session, papers: list[Paper]) -> tuple[str, list[dict]]:
    citations: list[dict] = []
    lines = [LOCAL_BANNER, "## 基于资料库的研究缺口线索\n"]
    lines.append("以下线索来自论文原文中明确出现的局限、未来工作与未覆盖场景表述，属于**候选线索**，不等于对整个领域的空白判断。\n")
    found = 0
    for paper in papers:
        chunks = db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
        pool = [c for c in chunks if any(t in (c.tags or []) for t in ("limitation", "future-work", "conclusion", "discussion"))] or chunks[-3:]
        for chunk in pool[:3]:
            keyword_hits = [s for s in split_sentences(chunk.text) if re.search(r"limitation|future|however|remain|unclear|not (?:yet|addressed)|局限|不足|未来|尚未|有待", s, re.I)]
            for sentence in keyword_hits[:1]:
                citations.append(
                    {
                        "key": f"C{len(citations) + 1}",
                        "chunk_id": chunk.id,
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "paper_year": paper.year,
                        "section": chunk.section_title,
                        "page": chunk.page_start,
                        "page_end": chunk.page_end,
                        "quote": sentence[:1400],
                        "score": 1.0,
                        "kind": chunk.kind,
                        "tags": list(chunk.tags or []),
                    }
                )
                lines.append(f"- **{paper.title[:70]}**（第 {chunk.page_start} 页）：{sentence} [C{len(citations)}]")
                found += 1
    if not found:
        lines.append("- 资料库中的论文未显式讨论局限或未来工作，建议增加相关综述或后续工作论文后再分析。")
    lines.append("\n### 如何验证这些线索")
    lines.append("1. 检索引用该论文的后续工作，确认问题是否已被解决。")
    lines.append("2. 对比同一数据集上的最新基线结果。")
    lines.append("3. 检查综述论文中对该方向的缺口描述。")
    return "\n".join(lines), citations


async def generative_gap_analysis(db: Session, config: ModelConfig | None, papers: list[Paper]) -> tuple[str, list[dict], bool]:
    if config is None:
        text, citations = local_gap_analysis(db, papers)
        return text, citations, True
    blocks, citations = [], []
    for paper in papers:
        context, cites = paper_context(db, paper, max_chars=4500)
        blocks.append(f"### {paper.title}\n{context}")
        for cite in cites:
            cite["key"] = f"C{len(citations) + 1}"
            citations.append(cite)
    messages = [
        {"role": "system", "content": system_prompt("explore")},
        {
            "role": "user",
            "content": "基于以下论文证据，识别研究缺口。要求：\n"
            "1. 区分\"论文作者明确指出的局限\"与\"你基于证据的推断\"；\n"
            "2. 每条缺口给出证据 [C#]、推理过程、以及验证方式；\n"
            "3. 明确说明仅凭这些论文不能断言整个领域的空白；\n"
            "4. 输出：已知共识 / 分歧 / 未解决问题 / 可验证假设 / 建议实验。\n\n" + "\n\n".join(blocks),
        },
    ]
    response = await LLMClient(config).complete(messages, temperature=0.35)
    return response["content"], citations, False

CRITICAL_CRITERIA = [
    "研究问题是否明确",
    "研究背景是否充分",
    "研究方法是否合理",
    "技术路线是否具有创新性",
    "实验设计是否充分",
    "实验数据是否支撑结论",
    "对比实验是否合理",
    "潜在局限性",
    "尚未解决的问题",
    "对后续研究的启发",
]


async def critical_review(db: Session, config: ModelConfig | None, paper: Paper) -> tuple[str, list[dict], bool]:
    if config is None:
        chunks = db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
        citations: list[dict] = []
        lines = [LOCAL_BANNER, f"## 《{paper.title}》结构化证据审查\n"]
        mapping = [
            ("研究问题", ("abstract", "introduction")),
            ("研究方法", ("method",)),
            ("实验设计", ("experiment", "result")),
            ("结论", ("conclusion",)),
            ("局限", ("limitation", "discussion", "future-work")),
        ]
        for label, tags in mapping:
            pool = [c for c in chunks if any(t in (c.tags or []) for t in tags)]
            lines.append(f"### {label}")
            if not pool:
                lines.append("- 论文中未检测到对应章节，建议人工核对。")
                continue
            for chunk in pool[:2]:
                sentence = pick_sentences(chunk.text, label, 1)[0]
                citations.append(
                    {
                        "key": f"C{len(citations) + 1}", "chunk_id": chunk.id, "paper_id": paper.id,
                        "paper_title": paper.title, "paper_year": paper.year, "section": chunk.section_title,
                        "page": chunk.page_start, "page_end": chunk.page_end, "quote": sentence[:1400],
                        "score": 1.0, "kind": chunk.kind, "tags": list(chunk.tags or []),
                    }
                )
                lines.append(f"- {sentence} [C{len(citations)}]")
        lines.append("\n### 本地模式的能力边界")
        lines.append("上述内容只完成章节证据定位，不包含对方法优劣或创新性的独立判断。配置生成式模型后可获得逐条批判性评估。")
        return "\n".join(lines), citations, True

    context, citations = paper_context(db, paper, max_chars=11000)
    criteria = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(CRITICAL_CRITERIA))
    messages = [
        {"role": "system", "content": system_prompt("critical")},
        {
            "role": "user",
            "content": f"请对论文《{paper.title}》做结构化批判性评估。逐条回答：\n{criteria}\n\n"
            "每条给出：结论 / 原文证据 [C#] / 置信度（高/中/低）/ 不确定性来源。"
            "最后给出：这篇论文最值得跟进的一点、最需要警惕的一点。\n\n论文原文：\n" + context,
        },
    ]
    response = await LLMClient(config).complete(messages, temperature=0.25)
    return response["content"], citations, False


def local_fragment_compare(fragments: list[dict]) -> tuple[str, list[dict]]:
    lines = [LOCAL_BANNER, "## 片段对比证据表\n", "| 来源 | 位置 | 原文片段 |", "|---|---|---|"]
    citations = []
    for fragment in fragments:
        key = f"C{len(citations) + 1}"
        citations.append(
            {
                "key": key, "chunk_id": fragment.get("chunk_id") or f"fragment-{len(citations) + 1}",
                "paper_id": fragment.get("paper_id", ""), "paper_title": fragment.get("paper_title", "未知论文"),
                "paper_year": fragment.get("year"), "section": fragment.get("section", ""),
                "page": fragment.get("page", 1), "page_end": fragment.get("page", 1),
                "quote": fragment.get("text", "")[:1400], "score": 1.0, "kind": "fragment", "tags": ["fragment"],
            }
        )
        title = (fragment.get("paper_title") or "未知").replace("|", "/")[:40]
        text = (fragment.get("text") or "").replace("|", "/")[:220]
        lines.append(f"| {title} | p.{fragment.get('page', '?')} {fragment.get('section', '')} | {text} [{key}] |")
    lines.append("\n### 使用建议")
    lines.append("- 这些是你手动选择的片段，本地模式只做并列呈现。")
    lines.append("- 若需共同点/差异/优劣分析，请配置生成式模型后重新比较。")
    return "\n".join(lines), citations


async def fragment_compare(config: ModelConfig | None, fragments: list[dict], focus: str) -> tuple[str, list[dict], bool]:
    if config is None:
        text, citations = local_fragment_compare(fragments)
        return text, citations, True
    citations = []
    blocks = []
    for fragment in fragments:
        key = f"C{len(citations) + 1}"
        citations.append(
            {
                "key": key, "chunk_id": fragment.get("chunk_id") or f"fragment-{len(citations) + 1}",
                "paper_id": fragment.get("paper_id", ""), "paper_title": fragment.get("paper_title", "未知论文"),
                "paper_year": fragment.get("year"), "section": fragment.get("section", ""),
                "page": fragment.get("page", 1), "page_end": fragment.get("page", 1),
                "quote": fragment.get("text", "")[:1400], "score": 1.0, "kind": "fragment", "tags": ["fragment"],
            }
        )
        blocks.append(
            f"[{key}] 论文《{fragment.get('paper_title', '未知')}》 p.{fragment.get('page', '?')} "
            f"· {fragment.get('section', '')}\n{fragment.get('text', '')[:1800]}"
        )
    messages = [
        {"role": "system", "content": system_prompt("multi_paper")},
        {
            "role": "user",
            "content": f"用户手动挑选了 {len(fragments)} 个论文片段进行对比。关注点：{focus or '默认维度'}。\n"
            "输出：1) 共同点 2) 不同点 3) 技术差异 4) 优缺点 5) 研究条件差异 6) 可能的关联 7) 对研究的启发。"
            "每个判断必须带 [C#]，无证据处明确说明。\n\n" + "\n\n".join(blocks),
        },
    ]
    response = await LLMClient(config).complete(messages, temperature=0.25)
    return response["content"], citations, False