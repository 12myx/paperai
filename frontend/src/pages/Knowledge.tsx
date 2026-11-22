import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookMarked,
  Download,
  ExternalLink,
  History,
  Layers,
  Network,
  List,
  Pin,
  Pencil,
  PinOff,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { ApiError, api, downloadFile } from "../lib/api";
import type { Collection, GraphData, GraphNode, KnowledgeCluster, KnowledgeItem, KnowledgeVersion, Paper } from "../lib/types";
import { cn, KNOWLEDGE_KINDS, relativeTime, truncate } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Field, IconButton, Input, Modal, Select, Tabs, Textarea } from "../components/ui";
import { MarkdownView } from "../components/Markdown";

const KIND_TONE: Record<string, "accent" | "info" | "warn" | "neutral"> = {
  note: "neutral", summary: "accent", insight: "info", method: "warn", result: "accent", question: "info", quote: "neutral",
};

export function Knowledge() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [cluster, setCluster] = useState("");
  const [clusters, setClusters] = useState<KnowledgeCluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("grid");
  const [editor, setEditor] = useState<Partial<KnowledgeItem> | null>(null);
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState<KnowledgeItem | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState("md");
  const [exporting, setExporting] = useState(false);
  const [versionsFor, setVersionsFor] = useState<KnowledgeItem | null>(null);
  const [versions, setVersions] = useState<KnowledgeVersion[]>([]);
  const [versionLoading, setVersionLoading] = useState(false);
  const [duplicate, setDuplicate] = useState<{ candidate: KnowledgeItem; score: number } | null>(null);
  const [duplicatesOpen, setDuplicatesOpen] = useState(false);
  const [duplicatePairs, setDuplicatePairs] = useState<{ score: number; left: KnowledgeItem; right: KnowledgeItem }[]>([]);
  const [searchParams] = useSearchParams();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (query.trim()) params.set("query", query.trim());
      if (kind) params.set("kind", kind);
      if (cluster) params.set("cluster", cluster);
      const [itemResponse, paperResponse, collectionResponse, clusterResponse] = await Promise.all([
        api<{ items: KnowledgeItem[] }>("/knowledge?" + params.toString()),
        api<{ items: Paper[] }>("/papers?limit=100"),
        api<{ items: Collection[] }>("/collections"),
        api<{ items: KnowledgeCluster[] }>("/knowledge/clusters"),
      ]);
      setItems(itemResponse.items);
      setPapers(paperResponse.items);
      setCollections(collectionResponse.items);
      setClusters(clusterResponse.items);
    } catch {
      toast("无法加载知识库", "error");
    } finally {
      setLoading(false);
    }
  }, [query, kind, cluster, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus || !items.length) return;
    const item = items.find((entry) => entry.id === focus);
    if (item && editor?.id !== item.id) setEditor(item);
  }, [items, searchParams]);

  useEffect(() => {
    if (view !== "graph") return;
    setGraphLoading(true);
    api<GraphData>("/knowledge/graph")
      .then(setGraph)
      .catch(() => toast("无法加载知识图谱", "error"))
      .finally(() => setGraphLoading(false));
  }, [view, toast]);

  async function saveItem(force = false) {
    if (!editor?.title?.trim()) {
      toast("请填写标题", "error");
      return;
    }
    setSaving(true);
    try {
      if (editor.id) {
        await api("/knowledge/" + editor.id, {
          method: "PATCH",
          body: {
            title: editor.title,
            content: editor.content || "",
            kind: editor.kind || "note",
            tags: editor.tags || [],
            pinned: editor.pinned,
          },
        });
      } else {
        await api("/knowledge", {
          method: "POST",
          body: {
            title: editor.title,
            content: editor.content || "",
            kind: editor.kind || "note",
            tags: editor.tags || [],
            source_paper_id: editor.source_paper_id || null,
            source_page: editor.source_page || null,
            source_quote: editor.source_quote || null,
            force,
          },
        });
      }
      setEditor(null);
      setDuplicate(null);
      toast("知识条目已保存", "success");
      void load();
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.code === "duplicate_knowledge" && apiError.detail && typeof apiError.detail === "object") {
        const detail = apiError.detail as { candidate?: KnowledgeItem; score?: number };
        if (detail.candidate) {
          setDuplicate({ candidate: detail.candidate, score: detail.score || 0 });
          return;
        }
      }
      toast(apiError.message || "保存失败", "error");
    } finally {
      setSaving(false);
    }
  }

  async function togglePin(item: KnowledgeItem) {
    try {
      await api("/knowledge/" + item.id, { method: "PATCH", body: { pinned: !item.pinned } });
      setItems((current) => current.map((row) => (row.id === item.id ? { ...row, pinned: !row.pinned } : row)));
    } catch {
      toast("操作失败", "error");
    }
  }

  async function removeItem() {
    if (!toDelete) return;
    try {
      await api("/knowledge/" + toDelete.id, { method: "DELETE" });
      setItems((current) => current.filter((row) => row.id !== toDelete.id));
      setToDelete(null);
      toast("已删除", "success");
    } catch {
      toast("删除失败", "error");
    }
  }

  async function exportKnowledge(scope: "filtered" | "all") {
    const ids = (scope === "filtered" ? items : items).map((item) => item.id);
    if (ids.length === 0) {
      toast("没有可导出的条目", "info");
      return;
    }
    setExporting(true);
    try {
      const response = await api<{ export: { download_url: string; filename: string } }>("/exports", {
        method: "POST",
        body: { kind: "knowledge", format: exportFormat, title: "个人知识库导出", knowledge_ids: ids },
      });
      await downloadFile(response.export.download_url, response.export.filename);
      toast("知识库已导出", "success");
      setExportOpen(false);
    } catch {
      toast("导出失败", "error");
    } finally {
      setExporting(false);
    }
  }

  async function openVersions(item: KnowledgeItem) {
    setVersionsFor(item);
    setVersionLoading(true);
    setVersions([]);
    try {
      const response = await api<{ versions: KnowledgeVersion[] }>("/knowledge/" + item.id + "/versions");
      setVersions(response.versions);
    } catch (error) {
      toast((error as Error).message || "无法加载版本", "error");
    } finally {
      setVersionLoading(false);
    }
  }

  async function rollback(version: KnowledgeVersion) {
    if (!versionsFor) return;
    try {
      await api("/knowledge/" + versionsFor.id + "/versions/" + version.version + "/rollback", {
        method: "POST",
        body: { note: "回滚到 v" + version.version },
      });
      toast("已回滚到 v" + version.version, "success");
      await openVersions(versionsFor);
      void load();
    } catch (error) {
      toast((error as Error).message || "回滚失败", "error");
    }
  }

  async function mergePair(left: KnowledgeItem, right: KnowledgeItem) {
    try {
      await api("/knowledge/" + left.id + "/merge", {
        method: "POST",
        body: { source_ids: [right.id], note: "合并相似条目" },
      });
      setDuplicatePairs((current) => current.filter((pair) => !(pair.left.id === left.id && pair.right.id === right.id)));
      toast("已合并相似条目", "success");
      void load();
    } catch (error) {
      toast((error as Error).message || "合并失败", "error");
    }
  }

  async function openDuplicates() {
    setDuplicatesOpen(true);
    try {
      const response = await api<{ items: { score: number; left: KnowledgeItem; right: KnowledgeItem }[] }>("/knowledge/duplicates");
      setDuplicatePairs(response.items);
    } catch (error) {
      toast((error as Error).message || "无法检查相似条目", "error");
    }
  }

  const stats = useMemo(
    () => ({
      total: items.length,
      pinned: items.filter((item) => item.pinned).length,
      withSource: items.filter((item) => item.source_paper_id).length,
    }),
    [items],
  );

  return (
    <div className="page page-knowledge">
      <header className="page-head">
        <div>
          <span className="eyebrow">Knowledge base</span>
          <h1>个人知识库</h1>
          <p>{stats.total} 条知识 · {stats.withSource} 条可追溯到原文 · {stats.pinned} 条置顶</p>
        </div>
        <div className="page-head-actions">
          <Button variant="ghost" icon={<Layers size={15} />} onClick={() => void openDuplicates()}>
            相似条目
          </Button>
          <Button variant="secondary" icon={<Download size={15} />} onClick={() => setExportOpen(true)}>
            导出
          </Button>
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setEditor({ kind: "note", tags: [] })}>
            新建知识
          </Button>
        </div>
      </header>

      <div className="knowledge-toolbar">
        <div className="filter-search">
          <Search size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="混合检索标题、内容与标签" />
        </div>
        <div className="filter-chips">
          <button className={cn("filter-chip", kind === "" && "active")} onClick={() => setKind("")}>全部</button>
          {KNOWLEDGE_KINDS.map((item) => (
            <button key={item.id} className={cn("filter-chip", kind === item.id && "active")} onClick={() => setKind(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className="cluster-chips">
          <button className={cn("filter-chip", cluster === "" && "active")} onClick={() => setCluster("")}>全部主题</button>
          {clusters.slice(0, 8).map((item) => (
            <button key={item.key} className={cn("filter-chip", cluster === item.key && "active")} onClick={() => setCluster(item.key)}>
              {item.label} <span className="cluster-count">{item.count}</span>
            </button>
          ))}
        </div>
        <div className="view-toggle">
          <button className={cn(view === "grid" && "active")} onClick={() => setView("grid")} aria-label="卡片视图"><List size={15} /></button>
          <button className={cn(view === "graph" && "active")} onClick={() => setView("graph")} aria-label="图谱视图"><Network size={15} /></button>
        </div>
      </div>

      {view === "graph" ? (
        <Card className="graph-card">
          {graphLoading && <div className="graph-loading">正在构建知识关联…</div>}
          {graph && graph.nodes.length === 0 && (
            <EmptyState title="还没有可展示的关联" description="保存知识片段并关联论文后，这里会显示知识网络。" />
          )}
          {graph && graph.nodes.length > 0 && (
            <GraphView
              data={graph}
              onOpenPaper={(id) => navigate("/app/papers/" + id)}
              onOpenKnowledge={(id) => {
                const item = items.find((row) => row.id === id);
                if (item) setEditor(item);
              }}
            />
          )}
          <p className="graph-legend">
            <span className="legend-dot paper" /> 论文
            <span className="legend-dot knowledge" /> 知识片段
            <span className="legend-dot tag" /> 标签
            <span className="legend-dot concept" /> 方法 / 数据 / 问题
            <span className="legend-line" /> 关联
          </p>
        </Card>
      ) : loading ? (
        <div className="knowledge-grid">
          {[0, 1, 2].map((index) => <div key={index} className="skeleton skeleton-card" />)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<BookMarked size={26} />}
          title="知识库还是空的"
          description="在阅读器中保存总结、在对话里保存结论，或手动新建一条研究笔记。每条知识都可以保留来源与页码。"
          action={<Button variant="primary" onClick={() => setEditor({ kind: "note", tags: [] })}>新建第一条知识</Button>}
        />
      ) : (
        <div className="knowledge-grid">
          {items.map((item) => (
            <article key={item.id} className="knowledge-card">
              <div className="knowledge-head">
                <Badge tone={KIND_TONE[item.kind] || "neutral"}>{KNOWLEDGE_KINDS.find((k) => k.id === item.kind)?.label || item.kind}</Badge>
                <div>
                  <IconButton label={item.pinned ? "取消置顶" : "置顶"} onClick={() => void togglePin(item)}>
                    {item.pinned ? <Pin size={14} /> : <PinOff size={14} />}
                  </IconButton>
                  <IconButton label="版本历史" onClick={() => void openVersions(item)}>
                    <History size={14} />
                  </IconButton>
                  <IconButton label="编辑" onClick={() => setEditor(item)}>
                    <Pencil size={14} />
                  </IconButton>
                  <IconButton label="删除" onClick={() => setToDelete(item)}>
                    <Trash2 size={14} />
                  </IconButton>
                </div>
              </div>
              <h3>{item.title}</h3>
              <p className="knowledge-preview">{truncate(item.content.replace(/[#>*_]/g, ""), 180)}</p>
              {item.tags.length > 0 && (
                <div className="paper-tags">
                  {item.tags.slice(0, 4).map((tag) => <span key={tag}>#{tag}</span>)}
                </div>
              )}
              {(item.auto_tags || []).length > 0 && (
                <div className="auto-tags">
                  <span className="auto-tags-label">自动</span>
                  {(item.auto_tags || []).slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              )}
              <div className="knowledge-foot">
                <span className="knowledge-version">v{item.version || 1}{item.cluster_label ? " · " + item.cluster_label : ""}</span>
                {item.source_paper_id ? (
                  <button onClick={() => navigate("/app/papers/" + item.source_paper_id + (item.source_page ? "?page=" + item.source_page : ""))}>
                    <ExternalLink size={12} /> {truncate(item.source_paper_title || "原文", 28)}{item.source_page ? " · p." + item.source_page : ""}
                  </button>
                ) : (
                  <span className="muted">无关联论文</span>
                )}
                <span>{relativeTime(item.updated_at)}</span>
              </div>
            </article>
          ))}
        </div>
      )}

      <Modal
        open={Boolean(editor)}
        onClose={() => setEditor(null)}
        title={editor?.id ? "编辑知识" : "新建知识"}
        subtitle="保留来源，才能在未来复用与核对。"
        size="lg"
        footer={
          <>
            {editor?.id && (
              <Button variant="soft" onClick={() => { setEditor(null); navigate("/app?knowledge=" + encodeURIComponent(editor.id || "")); }}>
                在 Chat 中使用
              </Button>
            )}
            <Button variant="ghost" onClick={() => setEditor(null)}>取消</Button>
            <Button variant="primary" loading={saving} onClick={() => void saveItem()}>保存</Button>
          </>
        }
      >
        {editor && (
          <div className="knowledge-editor">
            <Field label="标题">
              <Input value={editor.title || ""} onChange={(event) => setEditor({ ...editor, title: event.target.value })} placeholder="一句话概括这条知识" />
            </Field>
            <div className="editor-row">
              <Field label="类型">
                <Select value={editor.kind || "note"} onChange={(event) => setEditor({ ...editor, kind: event.target.value })}>
                  {KNOWLEDGE_KINDS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </Select>
              </Field>
              <Field label="关联论文（可选）">
                <Select value={editor.source_paper_id || ""} onChange={(event) => setEditor({ ...editor, source_paper_id: event.target.value || null })}>
                  <option value="">不关联</option>
                  {papers.map((paper) => <option key={paper.id} value={paper.id}>{truncate(paper.title, 50)}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="内容（支持 Markdown）">
              <Textarea rows={8} value={editor.content || ""} onChange={(event) => setEditor({ ...editor, content: event.target.value })} placeholder="写下结论、证据、方法与你的判断…" />
            </Field>
            <Field label="标签" hint="逗号分隔">
              <Input value={(editor.tags || []).join(", ")} onChange={(event) => setEditor({ ...editor, tags: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) })} />
            </Field>
            {editor.id && (
              <div className="knowledge-preview-block">
                <span className="muted small">预览</span>
                <MarkdownView content={editor.content || ""} />
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(duplicate)}
        onClose={() => setDuplicate(null)}
        title="发现相似知识"
        subtitle="默认不创建重复条目；你可以查看后决定是否仍然保存。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDuplicate(null)}>取消</Button>
            <Button variant="primary" loading={saving} onClick={() => void saveItem(true)}>仍然保存</Button>
          </>
        }
      >
        {duplicate && (
          <div className="duplicate-panel">
            <div className="duplicate-score">相似度 {Math.round(duplicate.score * 100)}%</div>
            <strong>{duplicate.candidate.title}</strong>
            <p>{truncate(duplicate.candidate.content.replace(/[#>*_]/g, ""), 260)}</p>
            <p className="muted small">建议先编辑现有条目，或合并内容后再保存。</p>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(versionsFor)}
        onClose={() => setVersionsFor(null)}
        title="版本历史"
        subtitle={versionsFor?.title}
        size="lg"
      >
        {versionLoading ? (
          <p className="muted">加载版本…</p>
        ) : versions.length === 0 ? (
          <EmptyState title="还没有版本记录" description="编辑或回滚后会自动生成新版本。" />
        ) : (
          <div className="version-list">
            {versions.map((version) => (
              <div key={version.id} className="version-card">
                <div className="version-head">
                  <strong>v{version.version}</strong>
                  <span>{relativeTime(version.created_at)}</span>
                  {version.note && <Badge tone="neutral">{version.note}</Badge>}
                  <Button size="sm" variant="ghost" icon={<History size={12} />} onClick={() => void rollback(version)}>
                    回滚
                  </Button>
                </div>
                <p>{truncate(version.content.replace(/[#>*_]/g, ""), 180)}</p>
                {version.changed_fields.length > 0 && <span className="version-fields">变更：{version.changed_fields.join("、")}</span>}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        open={duplicatesOpen}
        onClose={() => setDuplicatesOpen(false)}
        title="相似条目"
        subtitle="按字符 n-gram 相似度检测；阈值 0.82。"
        size="lg"
      >
        {duplicatePairs.length === 0 ? (
          <EmptyState title="没有发现相似条目" description="当前知识库中没有超过阈值的重复内容。" />
        ) : (
          <div className="duplicate-pair-list">
            {duplicatePairs.map((pair) => (
              <div key={pair.left.id + pair.right.id} className="duplicate-pair">
                <div>
                  <button onClick={() => { setDuplicatesOpen(false); setEditor(pair.left); }}>{pair.left.title}</button>
                  <span>↔</span>
                  <button onClick={() => { setDuplicatesOpen(false); setEditor(pair.right); }}>{pair.right.title}</button>
                </div>
                <div className="duplicate-pair-actions">
                  <Badge tone="warn">{Math.round(pair.score * 100)}%</Badge>
                  <Button size="sm" variant="ghost" icon={<Layers size={12} />} onClick={() => void mergePair(pair.left, pair.right)}>
                    合并到左侧
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title="导出知识库"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setExportOpen(false)}>取消</Button>
            <Button variant="primary" loading={exporting} onClick={() => void exportKnowledge("filtered")}>导出 {items.length} 条</Button>
          </>
        }
      >
        <Field label="格式">
          <Select value={exportFormat} onChange={(event) => setExportFormat(event.target.value)}>
            <option value="md">Markdown</option>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </Select>
        </Field>
        <p className="muted small">导出当前筛选结果，包含标题、内容、标签与来源论文。</p>
      </Modal>

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这条知识？"
        description={toDelete?.title}
        confirmLabel="删除"
        danger
        onConfirm={() => void removeItem()}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}

function GraphView({
  data,
  onOpenPaper,
  onOpenKnowledge,
}: {
  data: GraphData;
  onOpenPaper: (id: string) => void;
  onOpenKnowledge: (id: string) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const width = 880;
  const height = 560;
  const center = { x: width / 2, y: height / 2 };

  const layout = useMemo(() => {
    const papers = data.nodes.filter((node) => node.type === "paper");
    const knowledge = data.nodes.filter((node) => node.type === "knowledge");
    const concepts = data.nodes.filter((node) => !["paper", "knowledge"].includes(node.type));
    const positions: Record<string, { x: number; y: number; node: GraphNode }> = {};
    papers.forEach((node, index) => {
      const angle = (index / Math.max(papers.length, 1)) * Math.PI * 2 - Math.PI / 2;
      const radius = Math.min(150, 70 + papers.length * 8);
      positions[node.id] = { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius, node };
    });
    knowledge.forEach((node, index) => {
      const angle = (index / Math.max(knowledge.length, 1)) * Math.PI * 2 + Math.PI / 6;
      const radius = Math.min(220, 170 + knowledge.length * 1.5);
      positions[node.id] = { x: center.x + Math.cos(angle) * radius * 1.23, y: center.y + Math.sin(angle) * radius, node };
    });
    concepts.forEach((node, index) => {
      const angle = (index / Math.max(concepts.length, 1)) * Math.PI * 2 - Math.PI / 2 + 0.2;
      const radius = 275;
      positions[node.id] = { x: center.x + Math.cos(angle) * radius * 1.25, y: center.y + Math.sin(angle) * radius, node };
    });
    return positions;
  }, [data.nodes]);

  const connected = useMemo(() => {
    if (!hovered) return new Set<string>();
    const set = new Set<string>([hovered]);
    data.edges.forEach((edge) => {
      if (edge.source === hovered) set.add(edge.target);
      if (edge.target === hovered) set.add(edge.source);
    });
    return set;
  }, [hovered, data.edges]);

  return (
    <svg className="graph-svg" viewBox={"0 0 " + width + " " + height} role="img" aria-label="知识关联图">
      <defs>
        <radialGradient id="graphGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--accent-soft)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="var(--accent-soft)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx={center.x} cy={center.y} r="260" fill="url(#graphGlow)" />
      {data.edges.map((edge) => {
        const source = layout[edge.source];
        const target = layout[edge.target];
        if (!source || !target) return null;
        const active = hovered && (edge.source === hovered || edge.target === hovered);
        return (
          <line
            key={edge.id}
            x1={source.x}
            y1={source.y}
            x2={target.x}
            y2={target.y}
            className={cn("graph-edge", active && "active")}
          />
        );
      })}
      {Object.values(layout).map(({ node, x, y }) => {
        const isPaper = node.type === "paper";
        const isKnowledge = node.type === "knowledge";
        const dim = hovered && !connected.has(node.id);
        return (
          <g
            key={node.id}
            transform={"translate(" + x + "," + y + ")"}
            className={cn("graph-node", node.type, dim && "dim")}
            onMouseEnter={() => setHovered(node.id)}
            onMouseLeave={() => setHovered(null)}
            onClick={() => {
              const rawId = node.id.split(":")[1];
              if (isPaper) onOpenPaper(rawId);
              else if (isKnowledge) onOpenKnowledge(rawId);
            }}
          >
            <circle r={isPaper ? 13 : isKnowledge ? 9 : 6} className={"node-" + node.type} />
            <text y={isPaper ? 28 : isKnowledge ? 22 : 17} textAnchor="middle" className="node-label">
              {truncate(String(node.label), isPaper ? 26 : 22)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}