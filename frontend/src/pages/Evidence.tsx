import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileSearch,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, copyText } from "../lib/api";
import type { Evidence, EvidenceStats, Paper } from "../lib/types";
import { cn, EVIDENCE_TYPES, plainText, truncate } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, EmptyState, IconButton, Input, Select, Skeleton } from "../components/ui";

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
    void load();
  }, [load]);

  const verifiedRate = useMemo(
    () => (stats && stats.total > 0 ? Math.round((stats.verified / stats.total) * 100) : 0),
    [stats],
  );

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
      setToDelete(null);
      toast("证据已删除", "success");
      void load();
    } catch {
      toast("删除失败", "error");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page page-evidence">
      <header className="page-head">
        <div>
          <span className="eyebrow">Evidence System</span>
          <h1>证据库</h1>
          <p>所有 AI 结论背后的原文证据、推导与假设。未核对的内容不会被当作事实。</p>
        </div>
        <div className="page-head-actions">
          <Button variant="secondary" icon={<RefreshCw size={15} />} loading={backfilling} onClick={() => void backfill()}>
            回填历史证据
          </Button>
        </div>
      </header>

      <div className="evidence-stats">
        <Card className="evidence-stat">
          <ShieldCheck size={16} />
          <strong>{stats?.total ?? 0}</strong>
          <span>全部证据</span>
        </Card>
        <Card className="evidence-stat">
          <CheckCircle2 size={16} />
          <strong>{stats?.verified ?? 0}</strong>
          <span>已核对原文 · {verifiedRate}%</span>
        </Card>
        <Card className="evidence-stat">
          <FileSearch size={16} />
          <strong>{stats?.papers ?? 0}</strong>
          <span>覆盖论文</span>
        </Card>
        <Card className="evidence-stat">
          <AlertTriangle size={16} />
          <strong>{stats?.by_type?.insufficient ?? 0}</strong>
          <span>证据不足</span>
        </Card>
      </div>

      <div className="evidence-toolbar">
        <div className="filter-search">
          <FileSearch size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索证据原文、断言或章节" />
        </div>
        <div className="filter-chips">
          <button className={cn("filter-chip", type === "all" && "active")} onClick={() => setType("all")}>全部</button>
          {EVIDENCE_TYPES.map((item) => (
            <button key={item.id} className={cn("filter-chip", type === item.id && "active")} onClick={() => setType(item.id)}>
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

      {loading ? (
        <div className="evidence-list">{[0, 1, 2].map((index) => <Skeleton key={index} className="evidence-skeleton" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={26} />}
          title="还没有证据"
          description="向 AI 提问、生成总结或多论文对比后，引用会自动沉淀为可核对的证据；也可以从批注一键加入。"
          action={<Button variant="secondary" onClick={() => void backfill()} loading={backfilling}>从历史记录回填</Button>}
        />
      ) : (
        <div className="evidence-list">
          {items.map((evidence) => (
            <EvidenceRow
              key={evidence.id}
              evidence={evidence}
              onOpen={() => {
                if (!evidence.paper_id) return;
                const params = new URLSearchParams();
                if (evidence.page) params.set("page", String(evidence.page));
                if (evidence.chunk_id) params.set("chunk", evidence.chunk_id);
                navigate("/app/papers/" + evidence.paper_id + "?" + params.toString());
              }}
              onCopy={async () => {
                const ok = await copyText(evidence.quote || evidence.claim || "");
                toast(ok ? "已复制" : "复制失败", ok ? "success" : "error");
              }}
              onDelete={() => setToDelete(evidence)}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这条证据？"
        description="删除不会影响论文、批注或知识，只会移除这条可回溯记录。"
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
  onOpen,
  onCopy,
  onDelete,
}: {
  evidence: Evidence;
  onOpen: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const type = EVIDENCE_TYPES.find((item) => item.id === evidence.evidence_type);
  return (
    <article className={cn("evidence-row", "ev-" + evidence.evidence_type)}>
      <div className="evidence-row-main">
        <div className="evidence-row-top">
          <span className={cn("ev-type", "type-" + evidence.evidence_type)}>{type?.label || evidence.type_label}</span>
          <span className={cn("ev-verified", evidence.verified ? "ok" : "warn")}>
            {evidence.verified ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {evidence.verified ? "已核对原文" : "未核对"}
          </span>
          <span className="ev-confidence">置信度 {Math.round(evidence.confidence * 100)}%</span>
          <span className="evidence-source">来源：{sourceLabel(evidence.source_type)}</span>
        </div>
        {evidence.claim && evidence.claim.trim().length <= 240 && (
          <p className="evidence-claim">{plainText(evidence.claim, 220)}</p>
        )}
        {evidence.quote ? (
          <blockquote className="evidence-quote">{truncate(evidence.quote, 420)}</blockquote>
        ) : (
          <p className="evidence-empty-quote">该结论没有可展示的原文证据。</p>
        )}
        <div className="evidence-meta">
          {evidence.paper_title ? (
            <>
              <span>{evidence.paper_title}</span>
              {evidence.page && <span>p.{evidence.page}</span>}
              {evidence.section && <span>{evidence.section}</span>}
            </>
          ) : (
            <span className="muted">{evidence.evidence_type === "external" ? "需要外部验证" : "无关联论文"}</span>
          )}
          {evidence.verification_note && <span className="muted">{evidence.verification_note}</span>}
        </div>
      </div>
      <div className="evidence-row-actions">
        {evidence.can_locate && <Button size="sm" variant="ghost" icon={<ExternalLink size={13} />} onClick={onOpen}>原文</Button>}
        <IconButton label="复制证据" onClick={() => void onCopy()}><Copy size={14} /></IconButton>
        <IconButton label="删除证据" onClick={onDelete}><Trash2 size={14} /></IconButton>
      </div>
    </article>
  );
}

function sourceLabel(source: string): string {
  return {
    message: "对话",
    analysis: "AI 分析",
    annotation: "批注",
    knowledge: "知识",
    manual: "手动",
  }[source] || source;
}