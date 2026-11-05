import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookmarkCheck, BookmarkPlus, Image as ImageIcon, Loader2, Search, Sparkles, X } from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, apiPath } from "../lib/api";
import type { Figure, Paper } from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, EmptyState, Field, IconButton, Input, Modal, Tabs, Textarea } from "../components/ui";
import { MarkdownView } from "../components/Markdown";

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

export function Figures() {
  const { toast, model } = useApp();
  const navigate = useNavigate();
  const [figures, setFigures] = useState<Figure[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("all");
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<Figure | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (tab === "saved") params.set("saved", "true");
      if (query.trim()) params.set("query", query.trim());
      const [figureResponse, paperResponse] = await Promise.all([
        api<{ items: Figure[] }>("/figures?" + params.toString()),
        api<{ items: Paper[] }>("/papers?limit=100"),
      ]);
      setFigures(figureResponse.items);
      setPapers(paperResponse.items);
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
    if (active) setNote(active.note || "");
  }, [active]);

  async function toggleSaved(figure: Figure) {
    try {
      const response = await api<{ figure: Figure }>("/figures/" + figure.id, { method: "PATCH", body: { saved: !figure.saved } });
      setFigures((current) => current.map((item) => (item.id === figure.id ? response.figure : item)));
      if (active?.id === figure.id) setActive(response.figure);
      toast(response.figure.saved ? "已收藏到研究资料" : "已取消收藏", "success");
    } catch {
      toast("操作失败", "error");
    }
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
      if (detail?.code === "model_required") {
        toast("图表解释需要配置生成式模型", "info", detail.message);
      } else {
        toast((error as Error).message || "生成失败", "error");
      }
    } finally {
      setExplaining(false);
    }
  }

  const stats = useMemo(
    () => ({ total: figures.length, saved: figures.filter((figure) => figure.saved).length, tables: figures.filter((figure) => figure.kind === "table").length }),
    [figures],
  );

  return (
    <div className="page page-figures">
      <header className="page-head">
        <div>
          <span className="eyebrow">Figures & tables</span>
          <h1>图片与图表</h1>
          <p>{stats.total} 个图表 · {stats.saved} 个已收藏 · {stats.tables} 个表格 · 全部可追溯到论文页码</p>
        </div>
        <div className="filter-search" style={{ maxWidth: 280 }}>
          <Search size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按图注搜索" />
        </div>
      </header>

      <Tabs
        items={[
          { id: "all", label: "全部图表" },
          { id: "saved", label: "已收藏" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {loading ? (
        <div className="figure-grid">{[0, 1, 2].map((index) => <div key={index} className="skeleton" style={{ height: 220 }} />)}</div>
      ) : figures.length === 0 ? (
        <EmptyState
          icon={<ImageIcon size={26} />}
          title="还没有提取到图表"
          description="上传并解析论文后，系统会自动提取重要图片与表格。你也可以在阅读器中查看图表与图注。"
          action={<Button onClick={() => navigate("/app/papers")}>前往论文库</Button>}
        />
      ) : (
        <div className="figure-grid">
          {figures.map((figure) => (
            <FigureCard key={figure.id} figure={figure} onOpen={() => setActive(figure)} />
          ))}
        </div>
      )}

      <Modal
        open={Boolean(active)}
        onClose={() => setActive(null)}
        title={active ? (active.kind === "table" ? "表格" : "图表") + " · 第 " + active.page + " 页" : ""}
        size="xl"
        footer={
          <>
            <Button
              variant="ghost"
              icon={<BookmarkPlus size={14} />}
              onClick={() => active && void toggleSaved(active)}
            >
              {active?.saved ? "取消收藏" : "收藏到资料库"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => active && navigate("/app/papers/" + active.paper_id + "?page=" + active.page)}
            >
              打开原文页面
            </Button>
            <Button variant="primary" loading={saving} onClick={() => void saveNote()}>
              保存注释
            </Button>
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
                <Badge tone="neutral">{active.kind === "table" ? "表格" : "图片"}</Badge>
                <span>{truncate(active.paper_title || "", 60)}</span>
              </div>
              <p className="figure-caption">{active.caption || "论文未提供图注"}</p>
              <Field label="我的注释">
                <Textarea rows={4} value={note} onChange={(event) => setNote(event.target.value)} placeholder="这个图表支持了哪个结论？有什么可疑之处？" />
              </Field>
              <div className="figure-ai">
                <div className="figure-ai-head">
                  <strong><Sparkles size={14} /> AI 图表解释</strong>
                  {!model?.configured && <Badge tone="warn">需配置模型</Badge>}
                </div>
                {active.ai_explanation ? (
                  <MarkdownView content={active.ai_explanation} />
                ) : (
                  <p className="muted small">让 AI 解释这张图展示什么、支持什么结论，以及读图时的局限。</p>
                )}
                <Button size="sm" variant="secondary" loading={explaining} onClick={() => void explain()}>
                  {active.ai_explanation ? "重新解释" : "生成解释"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function FigureCard({ figure, onOpen }: { figure: Figure; onOpen: () => void }) {
  const src = useImageUrl(figure.image_url);
  return (
    <button className="figure-card" onClick={onOpen}>
      <div className="figure-thumb">
        {src ? <img src={src} alt={figure.caption || "figure preview"} loading="lazy" /> : <div className="figure-placeholder"><Loader2 size={18} className="spin" /></div>}
        {figure.saved && <span className="figure-saved"><BookmarkCheck size={13} /></span>}
        <span className="figure-kind">{figure.kind === "table" ? "表格" : "图"}</span>
      </div>
      <div className="figure-meta">
        <strong>{truncate(figure.caption || "无图注", 80)}</strong>
        <span>{truncate(figure.paper_title || "", 44)} · p.{figure.page}</span>
      </div>
    </button>
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