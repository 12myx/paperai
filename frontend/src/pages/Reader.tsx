import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import type { PDFDocumentProxy } from "pdfjs-dist";
import pdfWorker from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import {
  ArrowLeft,
  BookmarkPlus,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Highlighter,
  Languages,
  ListTree,
  Loader2,
  MessageSquareText,
  Minus,
  NotebookPen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Quote,
  Search,
  ShieldCheck,
  Sparkles,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { useEvidence } from "../store/EvidenceContext";
import { api, copyText, downloadFile, streamChat } from "../lib/api";
import type { Annotation, Citation, HighlightRect, OutlineChunk, Paper, PaperSection, StreamEvent } from "../lib/types";
import { ANNOTATION_COLORS, cn, relativeTime, SUMMARY_MODES, truncate } from "../lib/utils";
import { Badge, Button, ConfirmDialog, EmptyState, Field, IconButton, Input, Modal, Select, Spinner, Tabs, Textarea } from "../components/ui";
import { MarkdownView } from "../components/Markdown";
import { Uploader } from "../components/Uploader";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;

type PendingSelection = {
  text: string;
  page: number;
  rects: HighlightRect[];
  x: number;
  y: number;
};

type EditorState = {
  selection: PendingSelection;
  color: string;
  note: string;
  tags: string;
};

export function Reader() {
  const { paperId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast, settings, model } = useApp();
  const { openEvidence } = useEvidence();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [outline, setOutline] = useState<{ sections: PaperSection[]; chunks: OutlineChunk[] }>({ sections: [], chunks: [] });
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [scale, setScale] = useState(1.0);
  const [currentPage, setCurrentPage] = useState(Number(searchParams.get("page")) || 1);
  const [leftTab, setLeftTab] = useState("outline");
  const [colorFilter, setColorFilter] = useState<string>("");
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [editingAnnotation, setEditingAnnotation] = useState<Annotation | null>(null);
  const [translation, setTranslation] = useState<{ text: string; result: string; loading: boolean; error: string | null; target: string } | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState("pdf");
  const [exporting, setExporting] = useState(false);
  const [aiOpen, setAiOpen] = useState(true);
  const [summaryMode, setSummaryMode] = useState("abstract");
  const [summary, setSummary] = useState<{ content: string; citations: Citation[]; loading: boolean; local: boolean; error: string | null; label: string; analysisId?: string; evidenceCount?: number } | null>(null);
  const [extractInstruction, setExtractInstruction] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [question, setQuestion] = useState("");
  const [ask, setAsk] = useState<{ answer: string; citations: Citation[]; streaming: boolean; steps: { label: string; status: string }[]; error: string | null; serverId?: string }>({
    answer: "", citations: [], streaming: false, steps: [], error: null,
  });
  const [deleted, setDeleted] = useState<Annotation | null>(null);
  const [flashPage, setFlashPage] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Annotation | null>(null);
  const [savedSummary, setSavedSummary] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const askAbort = useRef<AbortController | null>(null);
  const userZoomed = useRef(false);

  /* ---------------------------------------------------------------- load */
  const loadPaper = useCallback(async () => {
    try {
      const response = await api<Paper>("/papers/" + paperId);
      setPaper(response);
      setPaperError(null);
    } catch (error) {
      setPaperError((error as Error).message || "无法加载论文");
    }
  }, [paperId]);

  useEffect(() => {
    void loadPaper();
  }, [loadPaper]);

  useEffect(() => {
    if (!paper || paper.status !== "processing") return;
    const timer = window.setInterval(() => void loadPaper(), 2500);
    return () => window.clearInterval(timer);
  }, [paper, loadPaper]);

  useEffect(() => {
    if (!paper || paper.status !== "ready") return;
    void api<{ sections: PaperSection[]; chunks: OutlineChunk[] }>("/papers/" + paper.id + "/outline")
      .then(setOutline)
      .catch(() => undefined);
    void api<{ items: Annotation[] }>("/annotations?paper_id=" + paper.id)
      .then((response) => setAnnotations(response.items))
      .catch(() => undefined);
  }, [paper]);

  useEffect(() => {
    if (!paper || paper.status !== "ready") return;
    let cancelled = false;
    let document: PDFDocumentProxy | null = null;
    (async () => {
      try {
        const response = await fetch("/api/papers/" + paper.id + "/file", {
          headers: { Authorization: "Bearer " + (localStorage.getItem("paperlens.token") || "") },
        });
        if (!response.ok) throw new Error("无法读取 PDF 文件");
        const data = new Uint8Array(await response.arrayBuffer());
        document = await pdfjsLib.getDocument({ data }).promise;
        if (cancelled) {
          void document.destroy();
          return;
        }
        setPdf(document);
        setPdfError(null);
      } catch (error) {
        setPdfError((error as Error).message || "PDF 渲染失败");
      }
    })();
    return () => {
      cancelled = true;
      if (document) void document.destroy();
    };
  }, [paper]);

  useEffect(() => {
    if (!pdf || userZoomed.current) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await pdf.getPage(1);
        const baseWidth = page.getViewport({ scale: 1 }).width;
        const container = scrollRef.current;
        if (!container || cancelled) return;
        const available = container.clientWidth - (window.innerWidth <= 720 ? 24 : 56);
        const next = Math.min(1.5, Math.max(0.6, available / baseWidth));
        setScale(Number(next.toFixed(2)));
      } catch {
        // keep the default scale if measurement fails
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pdf, aiOpen]);

  /* ---------------------------------------------------------------- page tracking */
  const scrollToPage = useCallback((page: number, chunk?: string | null) => {
    const element = pageRefs.current[page];
    if (!element) return;
    element.scrollIntoView({ behavior: "smooth", block: "start" });
    setFlashPage(page);
    window.setTimeout(() => setFlashPage(null), 1800);
    setCurrentPage(page);
    if (chunk) {
      const matched = outline.chunks.find((item) => item.id === chunk);
      if (matched) setLeftTab("outline");
    }
  }, [outline.chunks]);

  useEffect(() => {
    if (!pdf) return;
    const requested = Number(searchParams.get("page"));
    const saved = Number(localStorage.getItem("paperlens.reader." + paperId) || "0");
    const page = requested > 0 ? requested : saved;
    if (page && page > 0) {
      window.setTimeout(() => scrollToPage(page, searchParams.get("chunk")), 600);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !pdf) return;
    const onScroll = () => {
      let visible = 1;
      for (const [page, element] of Object.entries(pageRefs.current)) {
        if (!element) continue;
        const rect = element.getBoundingClientRect();
        if (rect.top <= 160 && rect.bottom > 160) {
          visible = Number(page);
          break;
        }
      }
      setCurrentPage(visible);
      localStorage.setItem("paperlens.reader." + paperId, String(visible));
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [pdf, paperId]);

  /* ---------------------------------------------------------------- selection */
  useEffect(() => {
    function handleSelection() {
      const active = window.getSelection();
      if (!active || active.isCollapsed || !active.toString().trim()) return;
      const range = active.getRangeAt(0);
      const node = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer.parentElement : (range.startContainer as HTMLElement);
      const pageElement = node?.closest?.(".pdf-page") as HTMLElement | null;
      if (!pageElement) return;
      const pageRect = pageElement.getBoundingClientRect();
      const rects = Array.from(range.getClientRects())
        .map((rect) => ({
          x: (rect.left - pageRect.left) / pageRect.width,
          y: (rect.top - pageRect.top) / pageRect.height,
          w: rect.width / pageRect.width,
          h: rect.height / pageRect.height,
        }))
        .filter((rect) => rect.w > 0.001 && rect.h > 0.001 && rect.y >= -0.01 && rect.y <= 1.01);
      if (rects.length === 0) return;
      const bounding = range.getBoundingClientRect();
      const text = active.toString().replace(/\s+/g, " ").trim();
      if (text.length < 2) return;
      const toolbarX = Math.min(Math.max(bounding.left + bounding.width / 2, 180), window.innerWidth - 180);
      const toolbarY = Math.min(Math.max(bounding.top, 84), window.innerHeight - 24);
      setSelection({
        text: text.slice(0, 2000),
        page: Number(pageElement.dataset.page),
        rects: rects.slice(0, 30),
        x: toolbarX,
        y: toolbarY,
      });
    }
    function clearOnClick(event: MouseEvent) {
      const target = event.target as HTMLElement;
      if (target.closest(".selection-toolbar") || target.closest(".annotation-layer")) return;
      window.setTimeout(() => {
        const active = window.getSelection();
        if (!active || active.isCollapsed) setSelection(null);
      }, 10);
    }
    document.addEventListener("mouseup", handleSelection);
    document.addEventListener("mousedown", clearOnClick);
    return () => {
      document.removeEventListener("mouseup", handleSelection);
      document.removeEventListener("mousedown", clearOnClick);
    };
  }, []);

  async function saveAnnotation(state: EditorState) {
    try {
      const response = await api<{ annotation: Annotation }>("/annotations", {
        method: "POST",
        body: {
          paper_id: paperId,
          page: state.selection.page,
          color: state.color,
          quote: state.selection.text,
          rects: state.selection.rects,
          note: state.note || null,
          tags: state.tags ? state.tags.split(",").map((item) => item.trim()).filter(Boolean) : [],
        },
      });
      setAnnotations((current) => [...current, response.annotation]);
      setEditor(null);
      setSelection(null);
      window.getSelection()?.removeAllRanges();
      toast("批注已保存", "success");
    } catch (error) {
      toast((error as Error).message || "保存批注失败", "error");
    }
  }

  async function quickHighlight(color: string) {
    if (!selection) return;
    await saveAnnotation({ selection, color, note: "", tags: "" });
  }

  async function addAnnotationEvidence(annotation: Annotation) {
    try {
      const response = await api<{ created: boolean }>("/evidence/from-annotation/" + annotation.id, { method: "POST" });
      toast(response.created ? "已加入证据库" : "该批注已在证据库中", "success");
      openEvidence("annotation", annotation.id, "批注证据");
    } catch (error) {
      toast((error as Error).message || "加入证据失败", "error");
    }
  }

  async function updateAnnotation(annotation: Annotation, patch: Partial<Annotation>) {
    try {
      const response = await api<{ annotation: Annotation }>("/annotations/" + annotation.id, { method: "PATCH", body: patch });
      setAnnotations((current) => current.map((item) => (item.id === annotation.id ? response.annotation : item)));
      setEditingAnnotation(null);
      toast("批注已更新", "success");
    } catch {
      toast("更新失败", "error");
    }
  }

  async function deleteAnnotation(annotation: Annotation) {
    try {
      await api("/annotations/" + annotation.id, { method: "DELETE" });
      setAnnotations((current) => current.filter((item) => item.id !== annotation.id));
      setDeleted(annotation);
      setConfirmDelete(null);
      setEditingAnnotation(null);
      window.setTimeout(() => setDeleted((current) => (current?.id === annotation.id ? null : current)), 12000);
      toast("批注已删除，可撤销", "info");
    } catch {
      toast("删除失败", "error");
    }
  }

  async function undoDelete() {
    if (!deleted) return;
    try {
      const response = await api<{ annotation: Annotation }>("/annotations/" + deleted.id + "/restore", { method: "POST" });
      setAnnotations((current) => [...current, response.annotation]);
      setDeleted(null);
      toast("已恢复批注", "success");
    } catch {
      toast("恢复失败", "error");
    }
  }

  /* ---------------------------------------------------------------- summary */
  async function runSummary(mode: string) {
    setSummaryMode(mode);
    setSavedSummary(false);
    setSummary({ content: "", citations: [], loading: true, local: false, error: null, label: SUMMARY_MODES.find((item) => item.id === mode)?.label || "总结" });
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; label: string; analysis_id?: string; evidence_count?: number }>(
        "/papers/" + paperId + "/summary",
        { method: "POST", body: { mode } },
      );
      setSummary({ content: response.content, citations: response.citations, loading: false, local: response.local, error: null, label: response.label, analysisId: response.analysis_id, evidenceCount: response.evidence_count });
    } catch (error) {
      setSummary({ content: "", citations: [], loading: false, local: false, error: (error as Error).message, label: "总结" });
    }
  }

  async function runAnalysis(kind: "critical" | "innovation" | "limitation" | "future") {
    setSavedSummary(false);
    const labels = { critical: "批判性评估", innovation: "创新性分析", limitation: "局限性分析", future: "未来研究方向" };
    setSummary({ content: "", citations: [], loading: true, local: false, error: null, label: labels[kind] });
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; analysis_id?: string; evidence_count?: number }>("/papers/" + paperId + "/analysis", {
        method: "POST",
        body: { mode: kind },
      });
      setSummary({ content: response.content, citations: response.citations, loading: false, local: response.local, error: null, label: labels[kind], analysisId: response.analysis_id, evidenceCount: response.evidence_count });
    } catch (error) {
      setSummary({ content: "", citations: [], loading: false, local: false, error: (error as Error).message, label: labels[kind] });
    }
  }

  async function runExtract() {
    const instruction = extractInstruction.trim();
    if (!instruction || extracting) return;
    setExtracting(true);
    setSavedSummary(false);
    setSummary({ content: "", citations: [], loading: true, local: false, error: null, label: "自定义提取" });
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; analysis_id?: string; evidence_count?: number }>("/papers/" + paperId + "/extract", {
        method: "POST",
        body: { instruction },
      });
      setSummary({ content: response.content, citations: response.citations, loading: false, local: response.local, error: null, label: "自定义提取", analysisId: response.analysis_id, evidenceCount: response.evidence_count });
      setExtractInstruction("");
    } catch (error) {
      setSummary({ content: "", citations: [], loading: false, local: false, error: (error as Error).message, label: "自定义提取" });
    } finally {
      setExtracting(false);
    }
  }

  /* ---------------------------------------------------------------- ask */
  async function askPaper() {
    const text = question.trim();
    if (!text || ask.streaming) return;
    setAsk({ answer: "", citations: [], streaming: true, steps: [], error: null });
    setQuestion("");
    const controller = new AbortController();
    askAbort.current = controller;
    let answer = "";
    const citations: Citation[] = [];
    let steps: { label: string; status: string }[] = [];
    await streamChat(
      { message: text, mode: "deep_read", scope_type: "papers", scope_ids: [paperId] },
      {
        signal: controller.signal,
        onError: (error) => {
          setAsk((current) => ({ ...current, streaming: false, error: error.message }));
          toast(error.message, "error");
        },
        onEvent: (event: StreamEvent) => {
          if (event.type === "delta") {
            answer += String(event.text || "");
            setAsk((current) => ({ ...current, answer, citations: [...citations] }));
          } else if (event.type === "step") {
            const step = event.step as { label: string; status: string; index: number };
            steps = [...steps.filter((item, index) => index !== step.index - 1), { label: step.label, status: step.status }];
            setAsk((current) => ({ ...current, steps }));
          } else if (event.type === "done") {
            const received = (event.citations as Citation[]) || [];
            citations.splice(0, citations.length, ...received);
            answer = String(event.content || answer);
            setAsk({ answer, citations: [...citations], streaming: false, steps, error: null, serverId: String(event.message_id || "") });
          } else if (event.type === "error") {
            setAsk((current) => ({ ...current, streaming: false, error: String(event.message) }));
          } else if (event.type === "notice") {
            toast(String(event.message), "info");
          }
        },
      },
    );
    setAsk((current) => ({ ...current, streaming: false }));
    askAbort.current = null;
  }

  async function saveSummaryToKnowledge() {
    if (!summary?.content) return;
    try {
      await api("/knowledge", {
        method: "POST",
        body: {
          title: truncate((paper?.title || "论文") + " · " + summary.label, 80),
          content: summary.content,
          kind: "summary",
          tags: ["summary", summaryMode],
          source_paper_id: paperId,
          source_page: summary.citations[0]?.page,
          source_quote: summary.citations[0]?.quote,
        },
      });
      setSavedSummary(true);
      toast("已保存到知识库", "success");
    } catch {
      toast("保存失败", "error");
    }
  }

  async function runExport() {
    setExporting(true);
    try {
      const response = await api<{ export: { download_url: string; filename: string } }>("/exports", {
        method: "POST",
        body: { kind: "paper-summary", format: exportFormat, title: (paper?.title || "论文总结") + " · PaperLens", paper_id: paperId },
      });
      await downloadFile(response.export.download_url, response.export.filename);
      toast("文件已导出", "success");
      setExportOpen(false);
    } catch (error) {
      toast((error as Error).message || "导出失败", "error");
    } finally {
      setExporting(false);
    }
  }

  async function translate(text: string) {
    const target = settings?.translation_language || "简体中文";
    setTranslation({ text, result: "", loading: true, error: null, target });
    try {
      const response = await api<{ content: string }>("/papers/" + paperId + "/translate", {
        method: "POST",
        body: { text: text.slice(0, 8000), target_language: target },
      });
      setTranslation({ text, result: response.content, loading: false, error: null, target });
    } catch (error) {
      const message = (error as { detail?: { message?: string } }).detail?.message || (error as Error).message;
      setTranslation({ text, result: "", loading: false, error: message, target });
    }
  }

  const filteredAnnotations = useMemo(
    () => annotations.filter((annotation) => !colorFilter || annotation.color === colorFilter),
    [annotations, colorFilter],
  );

  if (paperError) {
    return (
      <div className="reader-error">
        <EmptyState
          icon={<X size={26} />}
          title="无法打开这篇论文"
          description={paperError}
          action={<Button onClick={() => navigate("/app/papers")}>返回论文库</Button>}
        />
      </div>
    );
  }

  if (!paper || paper.status === "processing") {
    return (
      <div className="reader-loading">
        <Spinner size={26} />
        <h2>正在解析论文</h2>
        <p className="muted">提取章节、段落、图表与页码坐标。通常需要几秒钟。</p>
        <Button variant="ghost" onClick={() => navigate("/app/papers")}>
          返回论文库
        </Button>
      </div>
    );
  }

  if (paper.status === "failed") {
    return (
      <div className="reader-error">
        <EmptyState
          icon={<X size={26} />}
          title="论文解析失败"
          description={paper.error || "该 PDF 可能损坏或受到保护。"}
          action={
            <div className="row-gap">
              <Button variant="primary" onClick={async () => { await api("/papers/" + paper.id + "/reprocess", { method: "POST" }); void loadPaper(); }}>
                重新解析
              </Button>
              <Button variant="ghost" onClick={() => navigate("/app/papers")}>返回论文库</Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className={cn("reader", !aiOpen && "reader-wide")}>
      <header className="reader-head">
        <div className="reader-head-left">
          <IconButton label="返回论文库" onClick={() => navigate("/app/papers")}>
            <ArrowLeft size={18} />
          </IconButton>
          <div className="reader-title">
            <h1 title={paper.title}>{paper.title}</h1>
            <span>
              {paper.authors ? truncate(paper.authors, 60) + " · " : ""}
              {paper.year || "n.d."} · {paper.page_count} 页 · {annotations.length} 条批注
            </span>
          </div>
        </div>
        <div className="reader-head-right">
          <div className="zoom-controls">
            <IconButton label="缩小" onClick={() => { userZoomed.current = true; setScale((value) => Math.max(0.7, +(value - 0.1).toFixed(2))); }}>
              <Minus size={15} />
            </IconButton>
            <span>{Math.round(scale * 100)}%</span>
            <IconButton label="放大" onClick={() => { userZoomed.current = true; setScale((value) => Math.min(2.2, +(value + 0.1).toFixed(2))); }}>
              <Plus size={15} />
            </IconButton>
          </div>
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={() => setExportOpen(true)}>
            导出
          </Button>
          <IconButton label={aiOpen ? "收起 AI 面板" : "展开 AI 面板"} onClick={() => setAiOpen((open) => !open)}>
            {aiOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </IconButton>
        </div>
      </header>

      <div className="reader-body">
        <aside className="reader-left">
          <Tabs
            items={[
              { id: "outline", label: "目录" },
              { id: "pages", label: "页面" },
              { id: "annotations", label: "批注", count: annotations.length },
            ]}
            value={leftTab}
            onChange={setLeftTab}
          />
          <div className="reader-left-scroll">
            {leftTab === "outline" && (
              <nav className="outline-list">
                {outline.sections.length === 0 && <p className="muted small">未检测到章节结构，可通过页面导航浏览。</p>}
                {outline.sections.map((section) => (
                  <button
                    key={section.id}
                    className={cn("outline-item", "level-" + Math.min(section.level, 3))}
                    onClick={() => scrollToPage(section.page_start)}
                  >
                    <span>{section.title}</span>
                    <em>{section.page_start}</em>
                  </button>
                ))}
              </nav>
            )}

            {leftTab === "pages" && (
              <div className="page-grid">
                {Array.from({ length: pdf?.numPages || paper.page_count }, (_, index) => index + 1).map((page) => (
                  <button
                    key={page}
                    className={cn("page-chip", currentPage === page && "page-chip-active")}
                    onClick={() => scrollToPage(page)}
                  >
                    {page}
                  </button>
                ))}
              </div>
            )}

            {leftTab === "annotations" && (
              <div className="annotation-list">
                <div className="color-filter">
                  <button className={cn("color-dot", !colorFilter && "color-all")} style={{ background: "#9AA39D" }} onClick={() => setColorFilter("")} title="全部" />
                  {ANNOTATION_COLORS.map((color) => (
                    <button
                      key={color.id}
                      className={cn("color-dot", colorFilter === color.id && "color-active")}
                      style={{ background: color.color }}
                      onClick={() => setColorFilter(colorFilter === color.id ? "" : color.id)}
                      title={color.label}
                    />
                  ))}
                </div>
                {filteredAnnotations.length === 0 && (
                  <p className="muted small">选中 PDF 中的文字即可添加高亮与笔记。批注会保存到这篇论文，重新打开时自动恢复。</p>
                )}
                {filteredAnnotations.map((annotation) => (
                  <div key={annotation.id} className={cn("annotation-item", "ann-" + annotation.color)}>
                    <button className="annotation-main" onClick={() => { scrollToPage(annotation.page); setEditingAnnotation(annotation); }}>
                      <span className="annotation-page">p.{annotation.page}</span>
                      <p>{truncate(annotation.quote, 110)}</p>
                      {annotation.note && <em>{truncate(annotation.note, 80)}</em>}
                    </button>
                    <div className="annotation-actions">
                      <span>{ANNOTATION_COLORS.find((color) => color.id === annotation.color)?.label}</span>
                      <button onClick={() => setEditingAnnotation(annotation)} aria-label="编辑批注">
                        <NotebookPen size={13} />
                      </button>
                      <button onClick={() => setConfirmDelete(annotation)} aria-label="删除批注">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <section className="pdf-scroll" ref={scrollRef} onMouseUp={() => undefined}>
          {pdfError && <div className="reader-error-inline">{pdfError}</div>}
          {!pdf && !pdfError && (
            <div className="pdf-loading">
              <Spinner size={22} />
              <span>正在加载 PDF…</span>
            </div>
          )}
          {pdf &&
            Array.from({ length: pdf.numPages }, (_, index) => index + 1).map((pageNumber) => (
              <PdfPageView
                key={pageNumber}
                pdf={pdf}
                pageNumber={pageNumber}
                scale={scale}
                annotations={annotations.filter((annotation) => annotation.page === pageNumber)}
                flash={flashPage === pageNumber}
                register={(element) => {
                  pageRefs.current[pageNumber] = element;
                }}
                onAnnotationClick={setEditingAnnotation}
              />
            ))}
        </section>

        {aiOpen && (
          <aside className="reader-ai">
            <div className="ai-head">
              <div>
                <span className="eyebrow"><Sparkles size={12} /> Reading assistant</span>
                <h2>AI 阅读助手</h2>
              </div>
              <Badge tone={model?.configured ? "accent" : "warn"}>{model?.configured ? "生成式" : "本地抽取"}</Badge>
            </div>

            <div className="ai-summary">
              <h3><Quote size={14} /> 结构化总结</h3>
              <div className="summary-modes">
                {SUMMARY_MODES.slice(0, 8).map((mode) => (
                  <button
                    key={mode.id}
                    className={cn("summary-mode", summaryMode === mode.id && "active")}
                    onClick={() => void runSummary(mode.id)}
                    title={mode.hint}
                  >
                    {mode.label}
                  </button>
                ))}
                <Select
                  className="summary-more"
                  value=""
                  onChange={(event) => event.target.value && void runSummary(event.target.value)}
                  aria-label="更多总结模式"
                >
                  <option value="">更多…</option>
                  {SUMMARY_MODES.slice(8).map((mode) => (
                    <option key={mode.id} value={mode.id}>{mode.label}</option>
                  ))}
                </Select>
              </div>

              <div className="analysis-actions">
                <button onClick={() => void runAnalysis("critical")}>批判性评估</button>
                <button onClick={() => void runAnalysis("innovation")}>创新性</button>
                <button onClick={() => void runAnalysis("limitation")}>局限</button>
                <button onClick={() => void runAnalysis("future")}>未来方向</button>
              </div>

              <div className="extract-box">
                <Input
                  value={extractInstruction}
                  onChange={(event) => setExtractInstruction(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void runExtract();
                    }
                  }}
                  placeholder="自定义提取：例如 提取所有关于训练优化的内容"
                />
                <Button size="sm" variant="secondary" loading={extracting} onClick={() => void runExtract()} disabled={!extractInstruction.trim()}>
                  提取
                </Button>
              </div>

              {summary?.loading && (
                <div className="ai-loading"><Spinner size={16} /> 正在梳理章节与证据…</div>
              )}
              {summary?.error && <div className="ai-error">{summary.error}</div>}
              {summary && !summary.loading && summary.content && (
                <div className="summary-output">
                  <div className="summary-meta">
                    <span>{summary.label}</span>
                    {summary.local && <Badge tone="warn">抽取模式</Badge>}
                  </div>
                  <MarkdownView
                    content={summary.content}
                    onCite={(key) => {
                      const citation = summary.citations.find((item) => item.key === key);
                      if (citation) scrollToPage(citation.page);
                    }}
                  />
                  <div className="summary-actions">
                    <Button size="sm" variant="ghost" icon={savedSummary ? <CheckIcon /> : <BookmarkPlus size={13} />} onClick={() => void saveSummaryToKnowledge()} disabled={savedSummary}>
                      {savedSummary ? "已保存" : "保存到知识库"}
                    </Button>
                    {summary.analysisId && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<ShieldCheck size={13} />}
                        onClick={() => openEvidence("analysis", summary.analysisId!, summary.label)}
                      >
                        证据 {summary.evidenceCount ? summary.evidenceCount : ""}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" icon={<Download size={13} />} onClick={() => setExportOpen(true)}>
                      导出
                    </Button>
                  </div>
                </div>
              )}
              {!summary && (
                <p className="ai-hint">选择一种总结方式。每个要点都会引用原文页码，点击引用可跳转。</p>
              )}
            </div>

            <div className="ai-ask">
              <h3><MessageSquareText size={14} /> 追问这篇论文</h3>
              <div className="ai-ask-box">
                <Textarea
                  rows={2}
                  value={question}
                  placeholder="例如：消融实验是否足以支撑作者的结论？"
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void askPaper();
                    }
                  }}
                />
                <div className="ai-ask-controls">
                  <span className="muted small">{model?.configured ? "基于全文检索" : "本地抽取模式"}</span>
                  {ask.streaming ? (
                    <Button size="sm" variant="secondary" onClick={() => { askAbort.current?.abort(); setAsk((current) => ({ ...current, streaming: false })); }}>
                      停止
                    </Button>
                  ) : (
                    <Button size="sm" variant="primary" onClick={() => void askPaper()} disabled={!question.trim()}>
                      提问
                    </Button>
                  )}
                </div>
              </div>
              {ask.steps.length > 0 && ask.streaming && (
                <div className="ai-steps">
                  {ask.steps.map((step, index) => (
                    <span key={index} className={cn("ai-step", step.status)}>
                      {step.status === "running" ? <Loader2 size={11} className="spin" /> : "·"} {step.label}
                    </span>
                  ))}
                </div>
              )}
              {ask.error && <div className="ai-error">{ask.error}</div>}
              {ask.answer && (
                <div className="ask-output">
                  <MarkdownView
                    content={ask.answer}
                    onCite={(key) => {
                      const citation = ask.citations.find((item) => item.key === key);
                      if (citation) scrollToPage(citation.page);
                    }}
                  />
                  {ask.serverId && (
                    <div className="ask-evidence">
                      <Button size="sm" variant="ghost" icon={<ShieldCheck size={13} />} onClick={() => openEvidence("message", ask.serverId!, "本次追问")}>
                        证据视图
                      </Button>
                    </div>
                  )}
                  {ask.citations.length > 0 && (
                    <div className="ask-sources">
                      {ask.citations.slice(0, 3).map((citation) => (
                        <button key={citation.key} onClick={() => scrollToPage(citation.page)}>
                          <span>{citation.key}</span> p.{citation.page} · {truncate(citation.section, 24)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

      {selection && !editor && (
        <div className="selection-toolbar" style={{ left: selection.x, top: selection.y }}>
          <div className="toolbar-colors">
            {ANNOTATION_COLORS.map((color) => (
              <button
                key={color.id}
                className="toolbar-color"
                style={{ background: color.color }}
                title={color.label}
                onClick={() => void quickHighlight(color.id)}
              />
            ))}
          </div>
          <span className="toolbar-sep" />
          <button
            className="toolbar-action"
            onClick={() => setEditor({ selection, color: "yellow", note: "", tags: "" })}
          >
            <StickyNote size={14} /> 笔记
          </button>
          <button className="toolbar-action" onClick={() => void translate(selection.text)}>
            <Languages size={14} /> 翻译
          </button>
          <button
            className="toolbar-action"
            onClick={async () => {
              const ok = await copyText(selection.text);
              toast(ok ? "已复制选中文本" : "复制失败", ok ? "success" : "error");
            }}
          >
            <Quote size={14} /> 复制
          </button>
          <IconButton label="取消选择" onClick={() => { setSelection(null); window.getSelection()?.removeAllRanges(); }}>
            <X size={14} />
          </IconButton>
        </div>
      )}

      <Modal
        open={Boolean(editor)}
        onClose={() => setEditor(null)}
        title="添加批注"
        subtitle={editor ? "第 " + editor.selection.page + " 页" : undefined}
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditor(null)}>取消</Button>
            <Button variant="primary" onClick={() => editor && void saveAnnotation(editor)}>保存批注</Button>
          </>
        }
      >
        {editor && (
          <div className="annotation-editor">
            <blockquote className="editor-quote">{editor.selection.text}</blockquote>
            <Field label="标记含义">
              <div className="editor-colors">
                {ANNOTATION_COLORS.map((color) => (
                  <button
                    key={color.id}
                    className={cn("editor-color", editor.color === color.id && "active")}
                    onClick={() => setEditor({ ...editor, color: color.id })}
                  >
                    <span style={{ background: color.color }} />
                    {color.label}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="个人笔记">
              <Textarea
                rows={4}
                value={editor.note}
                onChange={(event) => setEditor({ ...editor, note: event.target.value })}
                placeholder="写下你的理解、疑问或与研究项目的关联…"
              />
            </Field>
            <Field label="标签" hint="用逗号分隔，例如：方法, 可复现">
              <Input value={editor.tags} onChange={(event) => setEditor({ ...editor, tags: event.target.value })} />
            </Field>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(editingAnnotation)}
        onClose={() => setEditingAnnotation(null)}
        title="编辑批注"
        subtitle={editingAnnotation ? "第 " + editingAnnotation.page + " 页" : undefined}
        size="md"
        footer={
          <>
            <Button variant="ghost" className="danger-text" icon={<Trash2 size={14} />} onClick={() => editingAnnotation && setConfirmDelete(editingAnnotation)}>
              删除
            </Button>
            <Button
              variant="secondary"
              icon={<ShieldCheck size={14} />}
              onClick={() => editingAnnotation && void addAnnotationEvidence(editingAnnotation)}
            >
              加入证据库
            </Button>
            <Button variant="primary" onClick={() => editingAnnotation && void updateAnnotation(editingAnnotation, { note: editingAnnotation.note, color: editingAnnotation.color, tags: editingAnnotation.tags })}>
              保存修改
            </Button>
          </>
        }
      >
        {editingAnnotation && (
          <div className="annotation-editor">
            <blockquote className="editor-quote">{editingAnnotation.quote}</blockquote>
            <div className="editor-meta">
              <span>{ANNOTATION_COLORS.find((color) => color.id === editingAnnotation.color)?.label}</span>
              <span>{relativeTime(editingAnnotation.created_at)}</span>
            </div>
            <Field label="颜色">
              <div className="editor-colors">
                {ANNOTATION_COLORS.map((color) => (
                  <button
                    key={color.id}
                    className={cn("editor-color", editingAnnotation.color === color.id && "active")}
                    onClick={() => setEditingAnnotation({ ...editingAnnotation, color: color.id as Annotation["color"] })}
                  >
                    <span style={{ background: color.color }} />
                    {color.label}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="笔记">
              <Textarea rows={4} value={editingAnnotation.note || ""} onChange={(event) => setEditingAnnotation({ ...editingAnnotation, note: event.target.value })} />
            </Field>
            <Field label="标签">
              <Input
                value={editingAnnotation.tags.join(", ")}
                onChange={(event) => setEditingAnnotation({ ...editingAnnotation, tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })}
              />
            </Field>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(translation)}
        onClose={() => setTranslation(null)}
        title="翻译与对照"
        subtitle={translation ? "目标语言：" + translation.target : undefined}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setTranslation(null)}>关闭</Button>
            {translation?.result && (
              <Button
                variant="secondary"
                icon={<BookmarkPlus size={14} />}
                onClick={async () => {
                  if (!translation?.result) return;
                  await api("/knowledge", {
                    method: "POST",
                    body: {
                      title: "翻译 · " + truncate(translation.text, 40),
                      content: "原文：\n" + translation.text + "\n\n译文：\n" + translation.result,
                      kind: "note",
                      tags: ["translation"],
                      source_paper_id: paperId,
                    },
                  });
                  toast("译文已保存", "success");
                }}
              >
                保存译文
              </Button>
            )}
          </>
        }
      >
        {translation && (
          <div className="translation-panel">
            <div className="translation-col">
              <span className="translation-label">原文</span>
              <p>{translation.text}</p>
            </div>
            <div className="translation-col">
              <span className="translation-label">译文</span>
              {translation.loading ? (
                <div className="ai-loading"><Spinner size={16} /> 正在翻译…</div>
              ) : translation.error ? (
                <div className="model-required">
                  <Languages size={20} />
                  <strong>需要配置生成式模型</strong>
                  <p>{translation.error}</p>
                  <Button size="sm" variant="primary" onClick={() => navigate("/app/settings?section=model")}>
                    前往配置 DeepSeek API Key
                  </Button>
                </div>
              ) : (
                <p>{translation.result}</p>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title="导出研究成果"
        subtitle="生成真实的 PDF / DOCX / Markdown 文件"
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setExportOpen(false)}>取消</Button>
            <Button variant="primary" loading={exporting} onClick={() => void runExport()}>
              生成并下载
            </Button>
          </>
        }
      >
        <div className="export-formats">
          {[
            { id: "pdf", label: "PDF", hint: "适合打印与分享" },
            { id: "docx", label: "DOCX", hint: "可继续编辑" },
            { id: "md", label: "Markdown", hint: "适合笔记工具" },
            { id: "txt", label: "TXT", hint: "纯文本" },
            { id: "json", label: "JSON", hint: "结构化数据" },
            { id: "csv", label: "CSV", hint: "表格数据" },
          ].map((format) => (
            <button
              key={format.id}
              className={cn("export-format", exportFormat === format.id && "active")}
              onClick={() => setExportFormat(format.id)}
            >
              <strong>{format.label}</strong>
              <span>{format.hint}</span>
            </button>
          ))}
        </div>
        <p className="muted small">
          将导出当前论文的结构化总结（若尚未生成，会先生成一次），包含引用页码。
        </p>
      </Modal>

      <ConfirmDialog
        open={Boolean(confirmDelete)}
        title="删除这条批注？"
        description="删除后可在 12 秒内撤销。"
        confirmLabel="删除"
        danger
        onConfirm={() => confirmDelete && void deleteAnnotation(confirmDelete)}
        onClose={() => setConfirmDelete(null)}
      />

      {deleted && (
        <div className="undo-bar">
          <span>批注已删除</span>
          <button onClick={() => void undoDelete()}>撤销</button>
        </div>
      )}
    </div>
  );
}

function CheckIcon() {
  return <span className="check-icon">✓</span>;
}

/* ------------------------------------------------------------------ PDF page */

function PdfPageView({
  pdf,
  pageNumber,
  scale,
  annotations,
  flash,
  register,
  onAnnotationClick,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  annotations: Annotation[];
  flash: boolean;
  register: (element: HTMLDivElement | null) => void;
  onAnnotationClick: (annotation: Annotation) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(pageNumber <= 3);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [rendered, setRendered] = useState(false);
  const renderTask = useRef<{ cancel: () => void; promise: Promise<void> } | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "900px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    renderTask.current?.cancel();
    renderTask.current = null;
    (async () => {
      try {
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale });
        if (cancelled) return;
        setSize({ width: viewport.width, height: viewport.height });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const context = canvas.getContext("2d");
        if (!context) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = viewport.width + "px";
        canvas.style.height = viewport.height + "px";
        const task = page.render({
          canvasContext: context,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
        });
        renderTask.current = task;
        await task.promise;
        if (cancelled) return;

        const textContent = await page.getTextContent();
        const layer = textRef.current;
        if (!layer) return;
        layer.innerHTML = "";
        layer.style.width = viewport.width + "px";
        layer.style.height = viewport.height + "px";
        for (const item of textContent.items) {
          if (!("str" in item) || !item.str) continue;
          const transform = pdfjsLib.Util.transform(viewport.transform, item.transform);
          const fontHeight = Math.hypot(transform[2], transform[3]);
          const span = document.createElement("span");
          span.textContent = item.str;
          span.style.position = "absolute";
          span.style.left = transform[4] + "px";
          span.style.top = transform[5] - fontHeight + "px";
          span.style.fontSize = fontHeight + "px";
          span.style.fontFamily = "sans-serif";
          span.style.color = "transparent";
          span.style.whiteSpace = "pre";
          span.style.transformOrigin = "0 0";
          span.style.cursor = "text";
          layer.appendChild(span);
          const targetWidth = item.width * viewport.scale;
          if (span.offsetWidth > 0 && targetWidth > 0) {
            span.style.transform = "scaleX(" + targetWidth / span.offsetWidth + ")";
          }
        }
        setRendered(true);
      } catch {
        // page-level render errors are non-fatal; the canvas stays blank
      }
    })();
    return () => {
      cancelled = true;
      renderTask.current?.cancel();
      renderTask.current = null;
    };
  }, [pdf, pageNumber, scale, visible]);

  return (
    <div
      className={cn("pdf-page", flash && "pdf-page-flash")}
      data-page={pageNumber}
      ref={(element) => {
        containerRef.current = element;
        register(element);
      }}
      style={size.width ? { width: size.width, height: size.height } : undefined}
    >
      <canvas ref={canvasRef} />
      <div className="text-layer" ref={textRef} />
      <div className="annotation-layer">
        {annotations.flatMap((annotation) =>
          (annotation.rects || []).map((rect, index) => (
            <button
              key={annotation.id + "-" + index}
              className={cn("highlight", "hl-" + annotation.color)}
              style={{
                left: rect.x * 100 + "%",
                top: rect.y * 100 + "%",
                width: rect.w * 100 + "%",
                height: rect.h * 100 + "%",
              }}
              title={annotation.note || annotation.quote}
              onClick={() => onAnnotationClick(annotation)}
            />
          )),
        )}
      </div>
      {!rendered && visible && <div className="page-skeleton" />}
      <span className="page-number">{pageNumber}</span>
    </div>
  );
}