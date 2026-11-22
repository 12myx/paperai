import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FilePlus2,
  FileText,
  FolderPlus,
  Loader2,
  MoreHorizontal,
  Search,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type { Collection, Paper, ProcessingJob } from "../lib/types";
import { cn, formatBytes, relativeTime, truncate } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Field, IconButton, Input, Modal, Select, Skeleton } from "../components/ui";
import { Uploader } from "../components/Uploader";
import { notifyUsageChanged } from "../lib/events";

export function Library() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const searchRef = useRef<HTMLInputElement>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [tags, setTags] = useState<{ name: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [tag, setTag] = useState("");
  const [collectionId, setCollectionId] = useState("");
  const [sort, setSort] = useState("recent");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [collectionModal, setCollectionModal] = useState(false);
  const [collectionName, setCollectionName] = useState("");
  const [collectionDesc, setCollectionDesc] = useState("");
  const [toDelete, setToDelete] = useState<Paper | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [addTarget, setAddTarget] = useState<Paper | null>(null);
  const [newCollectionFor, setNewCollectionFor] = useState("");
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);

  const refresh = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "200", sort });
      if (query.trim()) params.set("query", query.trim());
      if (status) params.set("status", status);
      if (favorite) params.set("favorite", "true");
      if (tag) params.set("tag", tag);
      if (collectionId) params.set("collection_id", collectionId);
      const [paperResponse, collectionResponse, tagResponse, jobResponse] = await Promise.all([
        api<{ items: Paper[] }>("/papers?" + params.toString()),
        api<{ items: Collection[] }>("/collections"),
        api<{ tags: { name: string; count: number }[] }>("/papers/tags"),
        api<{ items: ProcessingJob[] }>("/jobs?limit=8"),
      ]);
      setPapers(paperResponse.items);
      setCollections(collectionResponse.items);
      setTags(tagResponse.tags);
      setJobs(jobResponse.items);
    } catch {
      toast("无法加载论文库", "error");
    } finally {
      setLoading(false);
    }
  }, [query, status, favorite, tag, collectionId, sort, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (searchParams.get("focus") === "search") {
      searchRef.current?.focus();
    }
  }, [searchParams]);

  const hasProcessing = papers.some((paper) => paper.status === "processing");
  const activeJobs = jobs.filter((job) => ["queued", "running", "retrying", "failed"].includes(job.status));
  useEffect(() => {
    if (!hasProcessing && activeJobs.length === 0) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [hasProcessing, activeJobs.length, refresh]);

  const counts = useMemo(
    () => ({
      ready: papers.filter((paper) => paper.status === "ready").length,
      processing: papers.filter((paper) => paper.status === "processing").length,
      all: papers.length,
    }),
    [papers],
  );

  async function toggleFavorite(paper: Paper) {
    try {
      await api("/papers/" + paper.id, { method: "PATCH", body: { favorite: !paper.favorite } });
      setPapers((current) => current.map((item) => (item.id === paper.id ? { ...item, favorite: !item.favorite } : item)));
    } catch {
      toast("操作失败", "error");
    }
  }

  async function removePaper() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api("/papers/" + toDelete.id + "?confirm=true", { method: "DELETE" });
      toast("论文已删除", "success");
      notifyUsageChanged();
      setToDelete(null);
      void refresh();
    } catch (error) {
      toast((error as Error).message || "删除失败", "error");
    } finally {
      setDeleting(false);
    }
  }

  async function createCollection(addPaper?: Paper) {
    if (!collectionName.trim()) {
      toast("请填写合集名称", "error");
      return;
    }
    try {
      const response = await api<{ collection: Collection }>("/collections", {
        method: "POST",
        body: { name: collectionName.trim(), description: collectionDesc.trim() || null },
      });
      if (addPaper) {
        await api("/collections/" + response.collection.id + "/papers", { method: "POST", body: [addPaper.id] });
      }
      toast("合集已创建", "success");
      setCollectionModal(false);
      setCollectionName("");
      setCollectionDesc("");
      setNewCollectionFor("");
      setAddTarget(null);
      void refresh();
    } catch {
      toast("创建合集失败", "error");
    }
  }

  async function addToCollection(collection: Collection, paper: Paper) {
    try {
      await api("/collections/" + collection.id + "/papers", { method: "POST", body: [paper.id] });
      toast("已加入《" + collection.name + "》", "success");
      setAddTarget(null);
      void refresh();
    } catch {
      toast("加入合集失败", "error");
    }
  }

  return (
    <div className="page page-library">
      <header className="page-head">
        <div>
          <span className="eyebrow">Library</span>
          <h1>论文资料库</h1>
          <p>{counts.all} 篇论文 · {counts.ready} 篇已解析 · 所有内容仅你自己可见</p>
        </div>
        <div className="page-head-actions">
          <Button variant="secondary" icon={<FolderPlus size={15} />} onClick={() => setCollectionModal(true)}>
            新建合集
          </Button>
          <Button variant="primary" icon={<Upload size={15} />} onClick={() => setUploadOpen((open) => !open)}>
            上传论文
          </Button>
        </div>
      </header>

      {uploadOpen && (
        <div className="library-upload">
          <Uploader
            collectionId={collectionId || undefined}
            onBatchUploaded={() => void refresh()}
          />
        </div>
      )}

      <div className="filter-bar">
        <div className="filter-search">
          <Search size={16} />
          <Input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、作者或摘要"
          />
        </div>
        <div className="filter-chips">
          {[
            { id: "", label: "全部", count: counts.all },
            { id: "ready", label: "已解析", count: counts.ready },
            { id: "processing", label: "解析中", count: counts.processing },
            { id: "failed", label: "失败", count: 0 },
          ].map((item) => (
            <button
              key={item.id}
              className={cn("filter-chip", status === item.id && "active")}
              onClick={() => setStatus(item.id)}
            >
              {item.label}
              {item.count > 0 && <span>{item.count}</span>}
            </button>
          ))}
          <button className={cn("filter-chip", favorite && "active")} onClick={() => setFavorite((value) => !value)}>
            <Star size={13} /> 收藏
          </button>
        </div>
        <div className="filter-right">
          <Select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="排序">
            <option value="recent">最近上传</option>
            <option value="title">按标题</option>
            <option value="pages">按页数</option>
          </Select>
        </div>
      </div>

      {(collections.length > 0 || tags.length > 0) && (
        <div className="filter-sub">
          {collections.length > 0 && (
            <div className="filter-group">
              <span>合集</span>
              <button className={cn("tag-pill", collectionId === "" && "tag-active")} onClick={() => setCollectionId("")}>
                全部
              </button>
              {collections.map((collection) => (
                <button
                  key={collection.id}
                  className={cn("tag-pill", collectionId === collection.id && "tag-active")}
                  onClick={() => setCollectionId(collection.id)}
                >
                  {collection.name} <em>{collection.paper_count}</em>
                </button>
              ))}
            </div>
          )}
          {tags.length > 0 && (
            <div className="filter-group">
              <span>标签</span>
              {tag && (
                <button className="tag-pill tag-active" onClick={() => setTag("")}>
                  清除筛选
                </button>
              )}
              {tags.slice(0, 10).map((item) => (
                <button
                  key={item.name}
                  className={cn("tag-pill", tag === item.name && "tag-active")}
                  onClick={() => setTag(tag === item.name ? "" : item.name)}
                >
                  #{item.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="paper-grid">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="skeleton-card" />
          ))}
        </div>
      ) : papers.length === 0 ? (
        <EmptyState
          icon={<FileText size={26} />}
          title={query || status || tag || collectionId ? "没有匹配的论文" : "资料库还是空的"}
          description={
            query || status || tag || collectionId
              ? "尝试调整筛选条件，或清除搜索关键词。"
              : "上传第一篇 PDF。PaperLens 会自动解析章节、图表与页码坐标，让每个回答都能回到原文。"
          }
          action={
            <Button variant="primary" icon={<FilePlus2 size={15} />} onClick={() => setUploadOpen(true)}>
              上传论文
            </Button>
          }
        />
      ) : (
        <div className="paper-grid">
          {papers.map((paper, index) => (
            <article key={paper.id} className="paper-card">
              <div className={cn("paper-spine", "spine-" + (index % 5))} />
              <div className="paper-card-body">
                <div className="paper-card-top">
                  <StatusBadge paper={paper} />
                  <div className="paper-card-tools">
                    <IconButton
                      label={paper.favorite ? "取消收藏" : "收藏"}
                      className={cn(paper.favorite && "starred")}
                      onClick={() => void toggleFavorite(paper)}
                    >
                      <Star size={15} fill={paper.favorite ? "currentColor" : "none"} />
                    </IconButton>
                    <div className="menu-wrap">
                      <IconButton label="更多操作" onClick={() => setMenuFor(menuFor === paper.id ? null : paper.id)}>
                        <MoreHorizontal size={16} />
                      </IconButton>
                      {menuFor === paper.id && (
                        <div className="card-menu">
                          <button onClick={() => { setAddTarget(paper); setMenuFor(null); }}>
                            <FolderPlus size={14} /> 加入合集
                          </button>
                          <button onClick={() => { void api("/papers/" + paper.id + "/reprocess", { method: "POST" }).then(() => { toast("已重新排队解析", "info"); notifyUsageChanged(); void refresh(); }); setMenuFor(null); }}>
                            <Clock size={14} /> 重新解析
                          </button>
                          <button className="danger-text" onClick={() => { setToDelete(paper); setMenuFor(null); }}>
                            <Trash2 size={14} /> 删除论文
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <button className="paper-title" onClick={() => paper.status === "ready" && navigate("/app/papers/" + paper.id)}>
                  {paper.title}
                </button>
                <p className="paper-authors">
                  {paper.authors ? truncate(paper.authors, 80) : "作者未识别"} · {paper.year || "n.d."}
                </p>
                <p className="paper-abstract">{paper.abstract ? truncate(paper.abstract, 160) : "该论文尚未提取出摘要。"}</p>

                {paper.tags.length > 0 && (
                  <div className="paper-tags">
                    {paper.tags.slice(0, 3).map((item) => (
                      <span key={item}>#{item}</span>
                    ))}
                  </div>
                )}

                <div className="paper-card-foot">
                  <span>{paper.page_count || "—"} 页</span>
                  <span>{paper.chunks_count ? paper.chunks_count + " 切片" : formatBytes(paper.size_bytes)}</span>
                  <span>{relativeTime(paper.created_at)}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="paper-open"
                    disabled={paper.status !== "ready"}
                    onClick={() => navigate("/app/papers/" + paper.id)}
                  >
                    打开阅读
                  </Button>
                </div>

                {paper.status === "failed" && (
                  <div className="paper-failed">
                    <AlertTriangle size={13} /> {truncate(paper.error || "解析失败", 90)}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      <Modal
        open={collectionModal}
        onClose={() => setCollectionModal(false)}
        title="新建研究合集"
        subtitle="把同一主题的论文放在一起，便于多论文研究。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCollectionModal(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={() => void createCollection()}>
              创建
            </Button>
          </>
        }
      >
        <Field label="合集名称">
          <Input value={collectionName} onChange={(event) => setCollectionName(event.target.value)} placeholder="例如：RAG 与检索增强" autoFocus />
        </Field>
        <Field label="描述（可选）">
          <Input value={collectionDesc} onChange={(event) => setCollectionDesc(event.target.value)} placeholder="这个合集关注什么问题？" />
        </Field>
      </Modal>

      <Modal
        open={Boolean(addTarget)}
        onClose={() => setAddTarget(null)}
        title="加入合集"
        subtitle={addTarget ? "《" + truncate(addTarget.title, 40) + "》" : undefined}
        size="sm"
      >
        <div className="collection-add-list">
          {collections.map((collection) => (
            <button key={collection.id} onClick={() => addTarget && void addToCollection(collection, addTarget)}>
              <span className="collection-dot" style={{ background: collection.color }} />
              <span>{collection.name}</span>
              <small>{collection.paper_count} 篇</small>
            </button>
          ))}
          {collections.length === 0 && <p className="muted">还没有合集，先创建一个：</p>}
          <div className="collection-add-new">
            <Input
              value={newCollectionFor}
              onChange={(event) => setNewCollectionFor(event.target.value)}
              placeholder="新合集名称"
            />
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setCollectionName(newCollectionFor);
                setCollectionDesc("");
                void createCollection(addTarget || undefined);
              }}
            >
              创建并加入
            </Button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这篇论文？"
        description={
          toDelete
            ? "《" + truncate(toDelete.title, 50) + "》及其切片、批注与图表都会被永久删除，无法恢复。"
            : undefined
        }
        confirmLabel="永久删除"
        danger
        loading={deleting}
        onConfirm={() => void removePaper()}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}

function StatusBadge({ paper }: { paper: Paper }) {
  if (paper.status === "ready") {
    return (
      <span className="status status-ready">
        <CheckCircle2 size={12} /> 已解析
      </span>
    );
  }
  if (paper.status === "processing") {
    return (
      <span className="status status-processing">
        <Loader2 size={12} className="spin" /> 解析中
      </span>
    );
  }
  return (
    <span className="status status-failed">
      <AlertTriangle size={12} /> 解析失败
    </span>
  );
}