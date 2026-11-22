import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileSearch,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, copyText } from "../lib/api";
import type { Evidence, EvidenceStats, Paper } from "../lib/types";
import { cn, EVIDENCE_TYPES, truncate } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, EmptyState, IconButton, Input, Modal, Select, Skeleton } from "../components/ui";

const PAGE_SIZE = 30;

export function EvidenceLibrary() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<Evidence[]>([]);
  const [stats, setStats] = useState<EvidenceStats | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState("all");
  const [verified, setVerified] = useState("all");
  const [paperId, setPaperId] = useState("");
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [detail, setDetail] = useState<Evidence | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [toDelete, setToDelete] = useState<Evidence | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "300" });
      if (type !== "all") params.set("type", type);
      if (verified !== "all") params.set("verified", verified);
      if (paperId) params.set("paper_id", paperId);
      if (query.trim()) params.set("query", query.trim());
      const [evidenceResponse, statsResponse, paperResponse] = await Promise.all([
        api<{ items: Evidence[] }>("/evidence?" + params.toString()),
        api<EvidenceStats>("/evidence/stats"),
        api<{ items: Paper[] }>("/papers?limit=100"),
      ]);
      setItems(evidenceResponse.items);
      setStats(statsResponse);
      setPapers(paperResponse.items);
    } catch {
      toast("无法加载证据库", "error");
    } finally {
      setLoading(false);
    }
  }, [type, verified, paperId, query, toast]);

  useEffect(() => {
    setVisible(PAGE_SIZE);
    void load();
  }, [load]);

  const verifiedRate = useMemo(
    () => (stats && stats.total > 0 ? Math.round((stats.verified / stats.total) * 100) : 0),
    [stats],
  );
  const shown = items.slice(0, visible);

  async function backfill() {
    setBackfilling(true);
    try {
      const result = await api<{ created: number; skipped: number }>("/evidence/backfill", { method: "POST" });
      toast("历史证据回填完成", "success", "新增 " + result.created + " 条，跳过 " + result.skipped + " 条");
      await load();
    } catch (error) {
      toast((error as Error).message || "回填失败", "error");
    } finally {
      setBackfilling(false);
    }
  }

  async function remove() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api("/evidence/" + toDelete.id, { method: "DELETE" });
      setItems((current) => current.filter((item) => item.id !== toDelete.id));
      if (detail?.id === toDelete.id) setDetail(null);
      setToDelete(null);
      toast("证据已删除", "success");
      void load();
    } catch {
      toast("删除失败", "error");
    } finally {
      setDeleting(false);
    }
  }

  function openOriginal(evidence: Evidence) {
    if (!evidence.paper_id) return;
    const params = new URLSearchParams();
    if (evidence.page) params.set("page", String(evidence.page));
    if (evidence.chunk_id) params.set("chunk", evidence.chunk_id);
    navigate("/app/papers/" + evidence.paper_id + "?" + params.toString());
  }

  function openSource(evidence: Evidence) {
    if (evidence.source_url) navigate(evidence.source_url);
  }

  return (
    <div className="page page-evidence">
      <header className="page-head">
        <div>
          <span className="eyebrow">Evidence Review</span>
          <h1>证据检查</h1>
          <p>检查 AI 生成内容是否有原文支撑；证据不足不是事实，只提示你在纳入研究材料前保持谨慎。</p>
        </div>
        <div className="page-head-actions">
          <Button variant="secondary" icon={<RefreshCw size={15} />} loading={backfilling} onClick={() => void backfill()}>
            回填历史证据
          </Button>
        </div>
      </header>

      <div className="evidence-stats">
        <Card className="evidence-stat"><ShieldCheck size={16} /><strong>{stats?.total ?? 0}</strong><span>全部记录</span></Card>
        <Card className="evidence-stat"><CheckCircle2 size={16} /><strong>{stats?.verified ?? 0}</strong><span>已核对原文 · {verifiedRate}%</span></Card>
        <Card className="evidence-stat"><FileSearch size={16} /><strong>{stats?.papers ?? 0}</strong><span>覆盖论文</span></Card>
        <Card className="evidence-stat evidence-stat-warn"><AlertTriangle size={16} /><strong>{stats?.by_type?.insufficient ?? 0}</strong><span>需要谨慎</span></Card>
      </div>

      <div className="evidence-toolbar">
        <div className="filter-search">
          <FileSearch size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索生成结论、原文或章节" />
        </div>
        <div className="filter-chips">
          <button className={cn("filter-chip", type === "all" && "active")} onClick={() => setType("all")}>全部</button>
          {EVIDENCE_TYPES.map((item) => (
            <button key={item.id} className={cn("filter-chip", type === item.id && "active", item.id === "insufficient" && "filter-chip-warn")} onClick={() => setType(item.id)}>
              {item.short}
              <span>{stats?.by_type?.[item.id] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="evidence-filters-right">
          <Select value={paperId} onChange={(event) => setPaperId(event.target.value)} aria-label="按论文筛选">
            <option value="">全部论文</option>
            {papers.map((paper) => <option key={paper.id} value={paper.id}>{truncate(paper.title, 36)}</option>)}
          </Select>
          <Select value={verified} onChange={(event) => setVerified(event.target.value)} aria-label="按核验状态筛选">
            <option value="all">全部状态</option>
            <option value="true">已核对</option>
            <option value="false">未核对</option>
          </Select>
        </div>
      </div>

      <div className="evidence-list-head">
        <span>{loading ? "加载中…" : items.length + " 条结果"}</span>
        <span>点击结论可直接查看原文或生成来源</span>
      </div>

      {loading ? (
        <div className="evidence-list">{[0, 1, 2].map((index) => <Skeleton key={index} className="evidence-skeleton" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={26} />}
          title="还没有证据记录"
          description="向 AI 提问、生成总结或多论文对比后，引用会自动沉淀为可检查的证据。"
          action={<Button variant="secondary" onClick={() => void backfill()} loading={backfilling}>从历史记录回填</Button>}
        />
      ) : (
        <>
          <div className="evidence-list">
            {shown.map((evidence) => (
              <EvidenceRow
                key={evidence.id}
                evidence={evidence}
                onOpenOriginal={() => openOriginal(evidence)}
                onOpenSource={() => openSource(evidence)}
                onOpenDetail={() => setDetail(evidence)}
                onCopy={async () => {
                  const ok = await copyText(evidence.quote || evidence.claim || "");
                  toast(ok ? "已复制" : "复制失败", ok ? "success" : "error");
                }}
                onDelete={() => setToDelete(evidence)}
              />
            ))}
          </div>
          {visible < items.length && (
            <div className="evidence-load-more">
              <Button variant="secondary" onClick={() => setVisible((value) => value + PAGE_SIZE)}>
                加载更多（{items.length - visible}）
              </Button>
            </div>
          )}
        </>
      )}

      <EvidenceDetail
        evidence={detail}
        onClose={() => setDetail(null)}
        onOriginal={() => detail && openOriginal(detail)}
        onSource={() => detail && openSource(detail)}
        onCopy={async () => {
          if (!detail) return;
          const ok = await copyText(detail.quote || detail.claim || "");
          toast(ok ? "已复制" : "复制失败", ok ? "success" : "error");
        }}
        onDelete={() => { if (detail) { setToDelete(detail); setDetail(null); } }}
      />

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这条证据记录？"
        description="删除不会影响论文、对话或知识，只会移除这条可回溯记录。"
        confirmLabel="删除"
        danger
        loading={deleting}
        onConfirm={() => void remove()}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}

function EvidenceRow({
  evidence,
  onOpenOriginal,
  onOpenSource,
  onOpenDetail,
  onCopy,
  onDelete,
}: {
  evidence: Evidence;
  onOpenOriginal: () => void;
  onOpenSource: () => void;
  onOpenDetail: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const type = EVIDENCE_TYPES.find((item) => item.id === evidence.evidence_type);
  const insufficient = evidence.evidence_type === "insufficient";
  const title = evidence.claim || evidence.quote || "未命名结论";
  const sourceLine = evidence.paper_title
    ? evidence.paper_title + (evidence.page ? " · p." + evidence.page : "")
    : evidence.source_available && evidence.source_label
      ? "来源：" + evidence.source_label + (evidence.source_title ? " · " + evidence.source_title : "")
      : "来源不可用";
  return (
    <article className={cn("evidence-row", "ev-" + evidence.evidence_type, insufficient && "evidence-row-insufficient")}>
      <div className="evidence-row-main">
        <div className="evidence-row-top">
          <span className={cn("ev-type", "type-" + evidence.evidence_type)}>{type?.label || evidence.type_label}</span>
          <span className={cn("ev-verified", evidence.verified ? "ok" : "warn")}>
            {evidence.verified ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {evidence.verified ? "已核对原文" : "未核对"}
          </span>
          <span className="ev-confidence">置信度 {Math.round(evidence.confidence * 100)}%</span>
          <span className="evidence-source"><MessageSquare size={12} /> {evidence.source_label || sourceLabel(evidence.source_type)}</span>
        </div>
        <button className="evidence-claim-link" onClick={evidence.can_locate ? onOpenOriginal : onOpenDetail}>
          <strong>{truncate(title, 220)}</strong>
          <span>{evidence.can_locate ? "点击跳转原文" : "查看检查详情"} <ArrowUpRight size={12} /></span>
        </button>
        <div className="evidence-meta">
          <span>{sourceLine}</span>
          {insufficient && <span className="evidence-gap-tag">原文缺失</span>}
          {evidence.section && <span>{truncate(evidence.section, 50)}</span>}
        </div>
        {insufficient ? (
          <p className="evidence-gap-line">{evidence.gap_reason || "生成内容未定位到可核验的原文证据。"}</p>
        ) : evidence.quote ? (
          <blockquote className="evidence-quote evidence-quote-short">{truncate(evidence.quote, 180)}</blockquote>
        ) : null}
      </div>
      <div className="evidence-row-actions">
        {evidence.can_locate && <Button size="sm" variant="ghost" icon={<ExternalLink size={13} />} onClick={onOpenOriginal}>原文</Button>}
        {evidence.source_url && <Button size="sm" variant="ghost" icon={<ArrowUpRight size={13} />} onClick={onOpenSource}>生成来源</Button>}
        <Button size="sm" variant={insufficient ? "secondary" : "ghost"} onClick={onOpenDetail}>检查</Button>
        <IconButton label="复制证据" onClick={() => void onCopy()}><Copy size={14} /></IconButton>
        <IconButton label="删除证据" onClick={onDelete}><Trash2 size={14} /></IconButton>
      </div>
    </article>
  );
}

function EvidenceDetail({
  evidence,
  onClose,
  onOriginal,
  onSource,
  onCopy,
  onDelete,
}: {
  evidence: Evidence | null;
  onClose: () => void;
  onOriginal: () => void;
  onSource: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const insufficient = evidence?.evidence_type === "insufficient";
  return (
    <Modal
      open={Boolean(evidence)}
      onClose={onClose}
      title={insufficient ? "证据不足 · 需要谨慎" : "证据检查"}
      subtitle={evidence?.source_label ? "来源：" + evidence.source_label : undefined}
      size="lg"
      footer={
        <>
          {evidence?.can_locate && <Button variant="secondary" icon={<ExternalLink size={14} />} onClick={onOriginal}>打开原文位置</Button>}
          {evidence?.source_url && <Button variant="secondary" icon={<ArrowUpRight size={14} />} onClick={onSource}>打开生成内容</Button>}
          <Button variant="ghost" icon={<Copy size={14} />} onClick={onCopy}>复制</Button>
          <Button variant="ghost" className="danger-text" icon={<Trash2 size={14} />} onClick={onDelete}>删除</Button>
          <Button variant="primary" onClick={onClose}>关闭</Button>
        </>
      }
    >
      {evidence && (
        <div className="evidence-detail">
          <div className="evidence-detail-badges">
            <Badge tone={evidence.verified ? "accent" : "warn"}>{evidence.verified ? "已核对原文" : "未核对"}</Badge>
            <span>置信度 {Math.round(evidence.confidence * 100)}%</span>
            {insufficient && <Badge tone="danger">证据不足</Badge>}
          </div>
          <section>
            <h4>生成结论 / 待检查内容</h4>
            <p>{evidence.claim || "无结论文本"}</p>
          </section>
          {insufficient ? (
            <section className="evidence-detail-gap">
              <h4><AlertTriangle size={14} /> 为什么不足</h4>
              <p>{evidence.gap_reason || "生成内容未定位到可核验的原文证据。"}</p>
              <p className="muted small">请勿把这条结论当作已证实材料；请补充原文出处，或从研究材料中移除。</p>
            </section>
          ) : (
            <section>
              <h4>原文证据</h4>
              <blockquote className="evidence-detail-quote">{evidence.quote || "无原文引用"}</blockquote>
              {evidence.verification_note && <p className="muted small">{evidence.verification_note}</p>}
            </section>
          )}
          {evidence.source_available && (
            <section>
              <h4>生成来源</h4>
              <div className="evidence-source-card">
                <strong>{evidence.source_title || evidence.source_label}</strong>
                <p>{truncate(evidence.source_excerpt || "无可用生成内容摘要", 600)}</p>
              </div>
            </section>
          )}
          <section>
            <h4>位置</h4>
            <p className="muted">{evidence.paper_title || "无可定位论文"}{evidence.page ? " · p." + evidence.page : ""}{evidence.section ? " · " + evidence.section : ""}</p>
          </section>
        </div>
      )}
    </Modal>
  );
}

function sourceLabel(source: string): string {
  return {
    message: "AI 对话",
    analysis: "AI 分析",
    annotation: "批注",
    knowledge: "知识",
    artifact: "学术成果",
    artifact_summary: "学术成果",
    manual: "手动",
  }[source] || source;
}
