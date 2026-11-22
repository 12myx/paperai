import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowRight, BookmarkCheck, BookmarkPlus, FolderOpen, Image as ImageIcon, Loader2, Search, Sparkles, Table2 } from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, apiPath } from "../lib/api";
import type { Figure } from "../lib/types";
import { truncate } from "../lib/utils";
import { Badge, Button, EmptyState, Field, Input, Modal, Tabs, Textarea } from "../components/ui";
import { MarkdownView } from "../components/Markdown";

type FigureView = "featured" | "tables" | "snapshots" | "pending" | "saved";

function useImageUrl(url?: string | null) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let active = true;
    let objectUrl: string | null = null;
    fetch(apiPath(url), { headers: { Authorization: "Bearer " + (localStorage.getItem("paperlens.token") || "") } })
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error("图片加载失败"))))
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setSrc(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);
  return src;
}

function kindLabel(figure: Figure): string {
  const kind = figure.detected_kind || figure.kind;
  if (kind === "table") return "表格";
  if (kind === "page_snapshot") return "页面快照";
  if (kind === "unclassified") return "待确认";
  return "图";
}

export function Figures() {
  const { toast, model } = useApp();
  const navigate = useNavigate();
  const [figures, setFigures] = useState<Figure[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<FigureView>("featured");
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<Figure | null>(null);
  const [openPackage, setOpenPackage] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [searchParams] = useSearchParams();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "200", view: tab });
      if (query.trim()) params.set("query", query.trim());
      const response = await api<{ items: Figure[]; summary: Record<string, number> }>("/figures?" + params.toString());
      setFigures(response.items);
      setSummary(response.summary || {});
    } catch {
      toast("无法加载图表", "error");
    } finally {
      setLoading(false);
    }
  }, [tab, query, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus) return;
    const match = figures.find((entry) => entry.id === focus);
    if (match) setActive(match);
  }, [figures, searchParams]);

  useEffect(() => {
    if (active) setNote(active.note || "");
  }, [active]);

  async function updateFigure(figure: Figure, body: Record<string, unknown>, message: string) {
    try {
      const response = await api<{ figure: Figure }>("/figures/" + figure.id, { method: "PATCH", body });
      setFigures((current) => current.map((item) => (item.id === figure.id ? response.figure : item)));
      if (active?.id === figure.id) setActive(response.figure);
      toast(message, "success");
      void load();
    } catch {
      toast("操作失败", "error");
    }
  }

  async function rejectFigure(figure: Figure) {
    await updateFigure(figure, { ignored: true, review_status: "rejected" }, "已从图表库移除");
    setActive(null);
  }

  async function saveNote() {
    if (!active) return;
    setSaving(true);
    try {
      const response = await api<{ figure: Figure }>("/figures/" + active.id, { method: "PATCH", body: { note } });
      setFigures((current) => current.map((item) => (item.id === active.id ? response.figure : item)));
      setActive(response.figure);
      toast("注释已保存", "success");
    } catch {
      toast("保存失败", "error");
    } finally {
      setSaving(false);
    }
  }

  async function explain() {
    if (!active) return;
    setExplaining(true);
    try {
      const response = await api<{ figure: Figure }>("/figures/" + active.id + "/explain", { method: "POST" });
      setActive(response.figure);
      setFigures((current) => current.map((item) => (item.id === active.id ? response.figure : item)));
    } catch (error) {
      const detail = (error as { detail?: { code?: string; message?: string } }).detail;
      if (detail?.code === "model_required") toast("图表解释需要配置生成式模型", "info", detail.message);
      else toast((error as Error).message || "生成失败", "error");
    } finally {
      setExplaining(false);
    }
  }

  const groups = useMemo(() => {
    const map = new Map<string, { title: string; items: Figure[] }>();
    for (const figure of figures) {
      if (!map.has(figure.paper_id)) map.set(figure.paper_id, { title: figure.paper_title || "未命名论文", items: [] });
      map.get(figure.paper_id)?.items.push(figure);
    }
    return Array.from(map.entries()).map(([paperId, value]) => ({ paperId, ...value }));
  }, [figures]);

  return (
    <div className="page page-figures">
      <header className="page-head">
        <div>
          <span className="eyebrow">Figures & tables</span>
          <h1>图表与表格</h1>
          <p>{summary.featured ?? 0} 个精选图表 · {summary.tables ?? 0} 个表格 · {summary.snapshots ?? 0} 个页面快照 · {summary.saved ?? 0} 份视觉记录</p>
        </div>
        <div className="filter-search" style={{ maxWidth: 280 }}>
          <Search size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按图注或论文搜索" />
        </div>
      </header>

      <Tabs
        items={[
          { id: "featured", label: "精选图表", count: summary.featured },
          { id: "tables", label: "表格", count: summary.tables },
          { id: "snapshots", label: "页面快照", count: summary.snapshots },
          { id: "pending", label: "待确认", count: summary.pending },
          { id: "saved", label: "视觉记录", count: summary.saved },
        ]}
        value={tab}
        onChange={(value) => setTab(value as FigureView)}
      />

      {loading ? (
        <div className="figure-grid">{[0, 1, 2].map((index) => <div key={index} className="skeleton" style={{ height: 220 }} />)}</div>
      ) : figures.length === 0 ? (
        <EmptyState
          icon={tab === "tables" ? <Table2 size={26} /> : <ImageIcon size={26} />}
          title={tab === "featured" ? "还没有可确认的图表" : "这一层还没有内容"}
          description={tab === "featured" ? "系统已自动排除页面截图和装饰图。你可以到待确认检查低置信度条目，或在阅读器中查看论文原页。" : "切换到其他图层，或到阅读器中查看论文原页。"}
          action={<Button onClick={() => navigate("/app/papers")}>前往论文库</Button>}
        />
      ) : (
        <div className="figure-package-grid">
          {groups.map((group) => {
            const counts = group.items.reduce<Record<string, number>>((acc, item) => {
              const kind = item.detected_kind || item.kind;
              acc[kind] = (acc[kind] || 0) + 1;
              return acc;
            }, {});
            return (
              <button key={group.paperId} className="figure-package" onClick={() => setOpenPackage(group.paperId)}>
                <div className="figure-package-icon"><FolderOpen size={24} /></div>
                <div className="figure-package-body">
                  <span className="figure-package-kicker">论文资料包</span>
                  <strong>{truncate(group.title, 88)}</strong>
                  <div className="figure-package-counts">
                    <span>图 {counts.figure || 0}</span>
                    <span>表 {counts.table || 0}</span>
                    <span>快照 {counts.page_snapshot || 0}</span>
                    <span>待确认 {counts.unclassified || 0}</span>
                  </div>
                </div>
                <ArrowRight size={16} className="figure-package-arrow" />
              </button>
            );
          })}
        </div>
      )}

      <Modal
        open={Boolean(active)}
        onClose={() => setActive(null)}
        title={active ? kindLabel(active) + " · 第 " + active.page + " 页" : ""}
        size="xl"
        footer={
          <>
            {active && <Button variant="soft" onClick={() => { setActive(null); navigate("/app?image=" + encodeURIComponent(active.id)); }}>在 Chat 中提问</Button>}
            {active && <Button variant="ghost" icon={<BookmarkPlus size={14} />} onClick={() => void updateFigure(active, { saved: !active.saved }, active.saved ? "已取消视觉记录" : "已保存视觉记录")}>{active.saved ? "取消视觉记录" : "保存视觉记录"}</Button>}
            {active && !active.ignored && <Button variant="ghost" onClick={() => void rejectFigure(active)}>这不是图表</Button>}
            <Button variant="secondary" onClick={() => active && navigate("/app/papers/" + active.paper_id + "?page=" + active.page)}>打开原文页面</Button>
            <Button variant="primary" loading={saving} onClick={() => void saveNote()}>保存注释</Button>
          </>
        }
      >
        {active && (
          <div className="figure-detail">
            <div className="figure-detail-media">
              {active.image_url ? <FigureImage url={active.image_url} alt={active.caption || "figure"} /> : <TablePreview markdown={active.table_markdown} />}
            </div>
            <div className="figure-detail-side">
              <div className="figure-source">
                <Badge tone={active.detected_kind === "page_snapshot" ? "warn" : "neutral"}>{kindLabel(active)}</Badge>
                <span>{truncate(active.paper_title || "", 60)}</span>
                <Badge tone="neutral">质量 {active.quality_score ?? 0}</Badge>
              </div>
              <p className="figure-caption">{active.caption || "未识别图注 · 请结合原页核对"}</p>
              {active.detected_kind === "table" && active.table_markdown && (
                <details className="figure-table-text">
                  <summary>查看表格文本</summary>
                  <TablePreview markdown={active.table_markdown} />
                </details>
              )}
              {active.detected_kind === "page_snapshot" && <p className="figure-warning"><AlertTriangle size={13} /> 这是整页扫描，不是图表；仅用于定位原页。</p>}
              <Field label="我的注释">
                <Textarea rows={4} value={note} onChange={(event) => setNote(event.target.value)} placeholder="这个图表支持了哪个结论？有什么可疑之处？" />
              </Field>
              <div className="figure-ai">
                <div className="figure-ai-head"><strong><Sparkles size={14} /> AI 图表解释</strong>{!model?.configured && <Badge tone="warn">需配置模型</Badge>}</div>
                {active.ai_explanation ? <MarkdownView content={active.ai_explanation} /> : <p className="muted small">当前解释基于图注与表格文本，不等同于视觉模型读图。</p>}
                <Button size="sm" variant="secondary" loading={explaining} onClick={() => void explain()}>{active.ai_explanation ? "重新解释" : "生成解释"}</Button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(openPackage)}
        onClose={() => setOpenPackage(null)}
        title="论文图表资料包"
        subtitle={groups.find((group) => group.paperId === openPackage)?.title}
        size="lg"
        footer={<Button variant="secondary" onClick={() => setOpenPackage(null)}>关闭</Button>}
      >
        {(() => {
          const group = groups.find((item) => item.paperId === openPackage);
          if (!group) return <p className="muted small">资料包为空。</p>;
          return (
            <div className="figure-package-detail">
              <div className="figure-package-detail-head">
                <span>{group.items.length} 个条目</span>
                <small>点击条目查看大图或表格</small>
              </div>
              <div className="figure-package-list">
                {group.items.map((figure) => (
                  <button key={figure.id} className="figure-package-item" onClick={() => { setOpenPackage(null); setActive(figure); }}>
                    <span className={"figure-package-type figure-package-type-" + (figure.detected_kind || figure.kind)}>{kindLabel(figure)}</span>
                    <span className="figure-package-item-main">
                      <strong>{truncate(figure.caption || "未识别图注", 90)}</strong>
                      <small>p.{figure.page}{figure.needs_review ? " · 待确认" : ""}{figure.saved ? " · 已存视觉记录" : ""}</small>
                    </span>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
            </div>
          );
        })()}
      </Modal>
    </div>
  );
}

function FigureCard({ figure, onOpen }: { figure: Figure; onOpen: () => void }) {
  const src = useImageUrl(figure.image_url);
  return (
    <article className={"figure-card figure-card-" + (figure.detected_kind || figure.kind)}>
      <button className="figure-open" onClick={onOpen}>
        <div className="figure-thumb">
          {figure.detected_kind === "table" && !src ? <div className="figure-table-thumb"><Table2 size={22} /><span>表格</span></div> : src ? <img src={src} alt={figure.caption || "figure preview"} loading="lazy" /> : <div className="figure-placeholder"><Loader2 size={18} className="spin" /></div>}
          {figure.saved && <span className="figure-saved"><BookmarkCheck size={13} /></span>}
          <span className="figure-kind">{kindLabel(figure)}</span>
          {figure.needs_review && <span className="figure-review">待确认</span>}
        </div>
        <div className="figure-meta">
          <strong>{truncate(figure.caption || "未识别图注", 80)}</strong>
          <span>{truncate(figure.paper_title || "", 44)} · p.{figure.page}</span>
        </div>
      </button>
    </article>
  );
}

function FigureImage({ url, alt }: { url: string; alt: string }) {
  const src = useImageUrl(url);
  if (!src) return <div className="figure-placeholder large"><Loader2 size={22} className="spin" /></div>;
  return <img src={src} alt={alt} />;
}

function TablePreview({ markdown }: { markdown?: string | null }) {
  if (!markdown) return <div className="figure-placeholder large">无可用的表格文本</div>;
  return <MarkdownView content={markdown} className="table-markdown" />;
}