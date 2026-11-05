import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Copy, ExternalLink, FileSearch, ShieldCheck, X } from "lucide-react";
import { api, copyText } from "../lib/api";
import type { Evidence, EvidenceTarget } from "../lib/types";
import { cn, EVIDENCE_TYPES, plainText, truncate } from "../lib/utils";
import { Badge, IconButton, Spinner } from "./ui";
import { useApp } from "../store/AppContext";

const SOURCE_LABELS: Record<string, string> = {
  message: "本次回答",
  analysis: "本次分析",
  annotation: "这条批注",
  knowledge: "这条知识",
  manual: "手动创建",
};

export function EvidenceDrawer({ target, onClose }: { target: EvidenceTarget | null; onClose: () => void }) {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setLoading(true);
    setError(null);
    setFilter("all");
    api<{ items: Evidence[] }>(
      "/evidence?source_type=" + encodeURIComponent(target.sourceType) + "&source_id=" + encodeURIComponent(target.sourceId) + "&limit=200",
    )
      .then((response) => setItems(response.items))
      .catch((requestError) => setError((requestError as Error).message || "无法加载证据"))
      .finally(() => setLoading(false));
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [target, onClose]);

  if (!target) return null;

  const types = EVIDENCE_TYPES.filter((item) => items.some((evidence) => evidence.evidence_type === item.id));
  const visible = filter === "all" ? items : items.filter((item) => item.evidence_type === filter);
  const verifiedCount = items.filter((item) => item.verified).length;

  return (
    <div className="ev-root" role="dialog" aria-modal="true" aria-label="证据视图">
      <div className="ev-scrim" onClick={onClose} />
      <aside className="ev-drawer">
        <header className="ev-head">
          <div>
            <span className="eyebrow"><ShieldCheck size={12} /> Evidence System</span>
            <h2>证据视图</h2>
            <p>
              {SOURCE_LABELS[target.sourceType] || "该结果"}
              {target.label ? " · " + target.label : ""}
            </p>
          </div>
          <IconButton label="关闭证据视图" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </header>

        <div className="ev-summary">
          <span><strong>{items.length}</strong> 条证据</span>
          <span><strong>{verifiedCount}</strong> 条已核对</span>
          <span className={cn(verifiedCount < items.length && "warn")}>
            {items.length - verifiedCount} 条未核对
          </span>
        </div>

        {types.length > 1 && (
          <div className="ev-filters">
            <button className={cn("ev-chip", filter === "all" && "active")} onClick={() => setFilter("all")}>
              全部
            </button>
            {types.map((item) => (
              <button
                key={item.id}
                className={cn("ev-chip", filter === item.id && "active")}
                onClick={() => setFilter(item.id)}
              >
                {item.short}
                <em>{items.filter((evidence) => evidence.evidence_type === item.id).length}</em>
              </button>
            ))}
          </div>
        )}

        <div className="ev-body">
          {loading && (
            <div className="ev-loading"><Spinner size={18} /> 正在读取证据…</div>
          )}
          {error && <div className="ev-error">{error}</div>}
          {!loading && !error && visible.length === 0 && (
            <div className="ev-empty">
              <div className="ev-empty-icon"><FileSearch size={24} /></div>
              <h3>这个结果还没有可回溯证据</h3>
              <p>
                可能是资料库中没有相关论文、检索范围过窄，或模型没有给出可定位的原文。
                PaperLens 不会把无法核对的句子标记为证据。
              </p>
              <div className="ev-explain">
                {EVIDENCE_TYPES.map((item) => (
                  <div key={item.id}>
                    <span className={cn("ev-dot", "dot-" + item.id)} />
                    <strong>{item.label}</strong>
                    <em>{item.hint}</em>
                  </div>
                ))}
              </div>
            </div>
          )}
          {visible.map((evidence) => (
            <EvidenceCard
              key={evidence.id}
              evidence={evidence}
              onOpen={() => {
                if (!evidence.paper_id) return;
                const params = new URLSearchParams();
                if (evidence.page) params.set("page", String(evidence.page));
                if (evidence.chunk_id) params.set("chunk", evidence.chunk_id);
                navigate("/app/papers/" + evidence.paper_id + "?" + params.toString());
                onClose();
              }}
              onCopy={async () => {
                const text = [evidence.quote, evidence.paper_title, evidence.page ? "p." + evidence.page : ""]
                  .filter(Boolean)
                  .join(" — ");
                const ok = await copyText(text);
                toast(ok ? "证据已复制" : "复制失败", ok ? "success" : "error");
              }}
            />
          ))}
        </div>

        <footer className="ev-foot">
          <ShieldCheck size={13} />
          证据由论文切片与本地校验生成；未核对的内容不会被当作事实。
        </footer>
      </aside>
    </div>
  );
}

function EvidenceCard({
  evidence,
  onOpen,
  onCopy,
}: {
  evidence: Evidence;
  onOpen: () => void;
  onCopy: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const type = EVIDENCE_TYPES.find((item) => item.id === evidence.evidence_type);
  const confidence = Math.round(evidence.confidence * 100);
  const long = evidence.quote.length > 220;

  return (
    <article className={cn("ev-card", "ev-" + evidence.evidence_type)}>
      <div className="ev-card-top">
        <span className={cn("ev-type", "type-" + evidence.evidence_type)}>{type?.label || evidence.type_label}</span>
        <span className={cn("ev-verified", evidence.verified ? "ok" : "warn")}>
          {evidence.verified ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
          {evidence.verified ? "已核对原文" : "未核对"}
        </span>
        <span className="ev-confidence" title="证据置信度">{confidence}%</span>
      </div>

      {evidence.claim && evidence.claim.trim().length <= 220 && (
        <p className="ev-claim">{plainText(evidence.claim, 180)}</p>
      )}

      {evidence.quote ? (
        <>
          <blockquote className={cn("ev-quote", expanded && "expanded")}>{evidence.quote}</blockquote>
          {long && (
            <button className="ev-expand" onClick={() => setExpanded((value) => !value)}>
              {expanded ? "收起原文" : "展开原文"}
            </button>
          )}
        </>
      ) : (
        <div className="ev-no-quote">
          {evidence.evidence_type === "insufficient"
            ? "当前资料库中没有找到足以支撑该结论的原文。"
            : "该证据没有可展示的原文片段。"}
        </div>
      )}

      <div className="ev-meta">
        {evidence.paper_title ? (
          <>
            <span className="ev-paper">{truncate(evidence.paper_title, 54)}</span>
            {evidence.page && <span>p.{evidence.page}</span>}
            {evidence.section && <span>{truncate(evidence.section, 28)}</span>}
          </>
        ) : (
          <span className="muted">{evidence.evidence_type === "external" ? "需要外部文献验证" : "无关联论文"}</span>
        )}
      </div>

      {evidence.verification_note && (
        <p className="ev-note">{evidence.verification_note}</p>
      )}

      <div className="ev-actions">
        {evidence.can_locate && (
          <button onClick={onOpen}><ExternalLink size={12} /> 打开原文</button>
        )}
        {evidence.quote && <button onClick={onCopy}><Copy size={12} /> 复制</button>}
      </div>
    </article>
  );
}