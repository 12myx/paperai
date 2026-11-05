import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookmarkPlus,
  CheckCircle2,
  ExternalLink,
  GitBranch,
  Lightbulb,
  Network,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type {
  ConnectionEdge,
  ConnectionNode,
  ConnectionsData,
  IntelligenceScope,
  LandscapeData,
  LandscapeItem,
  OpportunitiesData,
  Opportunity,
  TrendsData,
} from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, EmptyState } from "./ui";

/* ------------------------------------------------------------------ landscape */

const SECTION_META: { key: keyof LandscapeData; label: string; hint: string }[] = [
  { key: "core_questions", label: "核心研究问题", hint: "论文画像中明确的研究问题" },
  { key: "technical_routes", label: "主要技术路线", hint: "方法层面的路线" },
  { key: "challenges", label: "技术挑战与局限", hint: "论文明确指出的局限" },
  { key: "future_directions", label: "未来方向线索", hint: "基于局限的候选方向" },
];

export function LandscapeView({ data, onOpen }: { data: LandscapeData; onOpen: (paperId: string, page?: number) => void }) {
  return (
    <div className="intel-landscape">
      <Card className="intel-overview-card">
        <div className="intel-section-head">
          <div>
            <span className="eyebrow">Landscape</span>
            <h2>资料库研究全景</h2>
          </div>
          <Badge tone={data.local ? "warn" : "accent"}>{data.local ? "本地抽取" : "生成式"}</Badge>
        </div>
        <p className="intel-overview-text">{data.overview}</p>
        <p className="p4-note">{data.note}</p>
        <div className="intel-scope-facts">
          <span>{data.scope.paper_count} 篇论文</span>
          <span>{data.scope.year_min || "未知"}–{data.scope.year_max || "未知"}</span>
          <span>{data.scope.boundary}</span>
        </div>
      </Card>

      <div className="intel-section-grid">
        {SECTION_META.map((section) => {
          const items = (data[section.key] as LandscapeItem[]) || [];
          return (
            <Card key={section.key} className="intel-section-card">
              <div className="intel-section-head">
                <div>
                  <h3>{section.label}</h3>
                  <p>{section.hint}</p>
                </div>
                <span className="intel-count">{items.length}</span>
              </div>
              {items.length === 0 ? (
                <p className="intel-empty">本次没有提取到可核对的条目。</p>
              ) : (
                <ul className="intel-item-list">
                  {items.map((item, index) => (
                    <li key={(item.evidence_key || "") + index}>
                      <p>{item.text}</p>
                      <div className="intel-item-foot">
                        <span>{truncate(item.paper_title, 38)}</span>
                        {item.page && (
                          <button onClick={() => onOpen(item.paper_id, item.page ?? undefined)}>
                            p.{item.page} <ExternalLink size={10} />
                          </button>
                        )}
                        {item.verified ? <CheckCircle2 size={11} className="text-success" /> : <AlertTriangle size={11} className="text-warning" />}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          );
        })}
      </div>

      <Card className="intel-representatives">
        <div className="intel-section-head">
          <div>
            <h3>代表性论文</h3>
            <p>本次范围内的方法与主要发现</p>
          </div>
        </div>
        <div className="intel-rep-list">
          {data.representative_papers.map((paper) => (
            <button key={paper.paper_id} onClick={() => onOpen(paper.paper_id)}>
              <strong>{truncate(paper.title, 70)}</strong>
              <span>{paper.year || "年份未知"}</span>
              <p><em>方法</em>{truncate(paper.method, 120)}</p>
              <p><em>发现</em>{truncate(paper.findings, 120)}</p>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ trends */

export function TrendsView({ data, onOpen }: { data: TrendsData; onOpen: (paperId: string, page?: number) => void }) {
  const max = Math.max(1, ...data.year_counts.map((item) => item.count));
  return (
    <div className="intel-trends">
      <Card className="intel-chart-card">
        <div className="intel-section-head">
          <div>
            <span className="eyebrow">Trends</span>
            <h2>资料库年份分布</h2>
          </div>
          <Badge tone="warn">本地统计</Badge>
        </div>
        <p className="p4-note">{data.note}</p>
        {data.year_counts.length === 0 ? (
          <EmptyState title="没有可用的年份数据" description="论文缺少出版年份，无法生成趋势；请补充元数据后重试。" />
        ) : (
          <div className="year-chart">
            {data.year_counts.map((item) => (
              <div key={item.year} className="year-bar">
                <span className="year-count">{item.count}</span>
                <div className="year-bar-track">
                  <div className="year-bar-fill" style={{ height: Math.max(8, (item.count / max) * 160) + "px" }} />
                </div>
                <span className="year-label">{item.year}</span>
              </div>
            ))}
            {data.unknown_year_count > 0 && <span className="chart-unknown">另有 {data.unknown_year_count} 篇年份未知</span>}
          </div>
        )}
      </Card>

      <div className="intel-two-col">
        <Card className="intel-section-card">
          <div className="intel-section-head">
            <div><h3>年度关键词（词频）</h3><p>来自标题与方法/发现文本；不是主题聚类</p></div>
          </div>
          <div className="keyword-years">
            {data.keyword_trends.map((year) => (
              <div key={year.year}>
                <strong>{year.year}</strong>
                <div>
                  {year.terms.length === 0 && <span className="muted small">无足够文本</span>}
                  {year.terms.map((term) => (
                    <span key={term.term} className="keyword-chip">{term.term}<em>{term.count}</em></span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="intel-section-card">
          <div className="intel-section-head">
            <div><h3>方法文本分布</h3><p>来自六维画像，按原文方法概括计数</p></div>
          </div>
          {data.method_counts.length === 0 ? (
            <p className="intel-empty">没有可用的方法文本。</p>
          ) : (
            <ul className="method-counts">
              {data.method_counts.map((item) => (
                <li key={item.method}>
                  <span>{truncate(item.method, 100)}</span>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          )}
          <div className="intel-observations">
            {data.observations.map((item) => <p key={item}>{item}</p>)}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ connections */

const NODE_COLORS: Record<string, string> = {
  paper: "#2c6b5d",
  method: "#3e6591",
  dataset: "#a97d3d",
  question: "#7b5ea7",
  knowledge: "#6d7671",
};

const NODE_LABELS: Record<string, string> = {
  paper: "论文",
  method: "方法",
  dataset: "数据集",
  question: "研究问题",
  knowledge: "知识",
};

export function ConnectionsView({ data, onOpen }: { data: ConnectionsData; onOpen: (paperId: string, page?: number) => void }) {
  const [selected, setSelected] = useState<string | null>(data.nodes.find((node) => node.type === "paper")?.id || null);
  const nodes = data.nodes.slice(0, 70);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const positions = useMemo(() => {
    const grouped: Record<string, ConnectionNode[]> = {};
    nodes.forEach((node) => {
      grouped[node.type] = grouped[node.type] || [];
      grouped[node.type].push(node);
    });
    const radii: Record<string, number> = { paper: 90, question: 170, method: 210, dataset: 250, knowledge: 285 };
    const result: Record<string, { x: number; y: number }> = {};
    Object.entries(grouped).forEach(([type, items]) => {
      const radius = radii[type] || 240;
      items.forEach((node, index) => {
        const angle = (index / Math.max(items.length, 1)) * Math.PI * 2 - Math.PI / 2 + (type === "method" ? 0.4 : 0);
        result[node.id] = { x: 430 + Math.cos(angle) * radius * 1.15, y: 300 + Math.sin(angle) * radius };
      });
    });
    return result;
  }, [nodes]);

  const connectedEdges = data.edges.filter((edge) => edge.source === selected || edge.target === selected);
  const selectedNode = selected ? nodeMap.get(selected) : null;

  return (
    <Card className="intel-connections">
      <div className="intel-section-head">
        <div>
          <span className="eyebrow">Connections</span>
          <h2>研究知识关联</h2>
          <p>{data.note}</p>
        </div>
        <div className="intel-legend">
          {Object.entries(NODE_LABELS).map(([type, label]) => (
            <span key={type}><i style={{ background: NODE_COLORS[type] }} />{label}</span>
          ))}
        </div>
      </div>

      <div className="connection-layout">
        <svg viewBox="0 0 860 600" className="connection-svg" role="img" aria-label="研究知识关联网络">
          {data.edges.map((edge) => {
            const source = positions[edge.source];
            const target = positions[edge.target];
            if (!source || !target) return null;
            const active = selected && (edge.source === selected || edge.target === selected);
            return (
              <line
                key={edge.id}
                x1={source.x} y1={source.y} x2={target.x} y2={target.y}
                className={cn("connection-edge", active && "active")}
              />
            );
          })}
          {nodes.map((node) => {
            const position = positions[node.id];
            if (!position) return null;
            const active = node.id === selected;
            return (
              <g
                key={node.id}
                transform={"translate(" + position.x + "," + position.y + ")"}
                className={cn("connection-node", node.type, active && "active")}
                onClick={() => setSelected(node.id)}
              >
                <circle r={node.type === "paper" ? 10 : node.type === "knowledge" ? 6 : 7} fill={NODE_COLORS[node.type] || "#6d7671"} />
                <text y={node.type === "paper" ? 24 : 19} textAnchor="middle" className="connection-label">
                  {truncate(node.label, node.type === "paper" ? 26 : 20)}
                </text>
              </g>
            );
          })}
        </svg>

        <aside className="connection-detail">
          {selectedNode ? (
            <>
              <Badge tone="neutral">{NODE_LABELS[selectedNode.type]}</Badge>
              <h3>{truncate(selectedNode.label, 80)}</h3>
              {selectedNode.type === "paper" && selectedNode.meta.paper_id && (
                <Button size="sm" variant="secondary" onClick={() => onOpen(String(selectedNode.meta.paper_id))}>
                  打开论文
                </Button>
              )}
              <p className="connection-detail-hint">与该节点相连的关系（含原文依据）</p>
              {connectedEdges.length === 0 && <p className="intel-empty">该节点没有已记录的关联。</p>}
              <div className="connection-edges">
                {connectedEdges.map((edge) => (
                  <ConnectionEdgeCard
                    key={edge.id}
                    edge={edge}
                    nodeMap={nodeMap}
                    selected={selected || ""}
                    onOpen={onOpen}
                  />
                ))}
              </div>
            </>
          ) : (
            <p className="intel-empty">点击左侧节点查看关联依据。</p>
          )}
        </aside>
      </div>
    </Card>
  );
}

function ConnectionEdgeCard({
  edge,
  nodeMap,
  selected,
  onOpen,
}: {
  edge: ConnectionEdge;
  nodeMap: Map<string, ConnectionNode>;
  selected: string;
  onOpen: (paperId: string, page?: number) => void;
}) {
  const otherId = edge.source === selected ? edge.target : edge.source;
  const other = nodeMap.get(otherId);
  const rawPaperId =
    edge.basis.paper_id ||
    (nodeMap.get(edge.source)?.type === "paper" ? nodeMap.get(edge.source)?.meta.paper_id : nodeMap.get(edge.target)?.meta.paper_id);
  const paperId = rawPaperId ? String(rawPaperId) : undefined;
  return (
    <div className="connection-edge-card">
      <div className="connection-edge-head">
        <GitBranch size={12} />
        <span>{edge.relation}</span>
        <strong>{other ? truncate(other.label, 34) : otherId}</strong>
      </div>
      {edge.basis.quote && <blockquote>{truncate(edge.basis.quote, 140)}</blockquote>}
      <div className="connection-edge-foot">
        {edge.basis.page && <span>p.{edge.basis.page}</span>}
        {paperId && (
          <button onClick={() => onOpen(String(paperId), edge.basis.page ?? undefined)}>
            原文 <ExternalLink size={10} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ opportunities */

export function OpportunitiesView({ data, onOpen }: { data: OpportunitiesData; onOpen: (paperId: string, page?: number) => void }) {
  const { toast } = useApp();
  return (
    <div className="intel-opportunities">
      <Card className="intel-scope-card">
        <div className="intel-section-head">
          <div>
            <span className="eyebrow">Opportunities</span>
            <h2>研究机会建议</h2>
          </div>
          <Badge tone={data.local ? "warn" : "accent"}>{data.local ? "启发式候选" : "生成式建议"}</Badge>
        </div>
        <p className="p4-note">{data.note}</p>
      </Card>
      {data.opportunities.length === 0 ? (
        <EmptyState
          icon={<Lightbulb size={26} />}
          title="没有足够证据提出研究机会"
          description="资料库中的论文没有明确写出局限或未来工作，或当前范围过小。不要为了数量凭空制造方向。"
        />
      ) : (
        <div className="opportunity-list">
          {data.opportunities.map((item) => (
            <OpportunityCard key={item.id} item={item} onOpen={onOpen} onSave={async () => {
              try {
                await api("/knowledge", {
                  method: "POST",
                  body: {
                    title: "研究机会 · " + truncate(item.title, 60),
                    content: [
                      "## 研究机会",
                      item.title,
                      "### 背景",
                      item.background,
                      "### 现有不足",
                      item.existing_gap,
                      "### 切入点",
                      item.entry_point,
                      "### 实验方案",
                      item.experiment_plan,
                      "### 风险",
                      item.risks,
                    ].join("\n\n"),
                    kind: "question",
                    tags: ["research-opportunity", "intelligence"],
                    source_paper_id: item.evidence?.paper_id,
                    source_page: item.evidence?.page,
                    source_quote: item.evidence?.quote,
                  },
                });
                toast("研究机会已保存到知识库", "success");
              } catch {
                toast("保存失败", "error");
              }
            }} />
          ))}
        </div>
      )}
    </div>
  );
}

function OpportunityCard({ item, onOpen, onSave }: { item: Opportunity; onOpen: (paperId: string, page?: number) => void; onSave: () => void }) {
  return (
    <Card className="opportunity-card">
      <div className="opportunity-head">
        <div>
          <div className="opportunity-badges">
            <Badge tone={item.ai_generated ? "accent" : "warn"}>{item.ai_generated ? "AI 建议" : "启发式候选"}</Badge>
            <Badge tone="neutral">难度 {item.difficulty || "待评估"}</Badge>
            {item.related_papers.length > 1 && <Badge tone="neutral">{item.related_papers.length} 篇论文</Badge>}
          </div>
          <h3>{item.title}</h3>
        </div>
        <Button size="sm" variant="ghost" icon={<BookmarkPlus size={13} />} onClick={onSave}>保存</Button>
      </div>
      <p className="opportunity-background">{item.background}</p>
      <div className="opportunity-fields">
        <div><span>现有不足</span><p>{item.existing_gap}</p></div>
        <div><span>切入点</span><p>{item.entry_point}</p></div>
        <div><span>实验方案</span><p>{item.experiment_plan}</p></div>
        <div><span>知识储备</span><p>{item.knowledge_needed}</p></div>
      </div>
      <div className="opportunity-risk"><ShieldCheck size={13} /> {item.risks}</div>
      {item.evidence?.page && (
        <button className="opportunity-evidence" onClick={() => onOpen(item.evidence.paper_id, item.evidence.page ?? undefined)}>
          <span>{item.evidence.evidence_key || "证据"}</span>
          p.{item.evidence.page} · {truncate(item.evidence.paper_title || "未知论文", 40)} · {truncate(item.evidence.quote || "", 90)}
          <ArrowRight size={11} />
        </button>
      )}
    </Card>
  );
}

export function ScopeBoundary({ scope }: { scope: IntelligenceScope }) {
  return (
    <div className="intel-boundary">
      <ShieldCheck size={14} />
      <span>
        {scope.boundary} · {scope.paper_count} 篇论文
        {scope.year_min ? ` · ${scope.year_min}–${scope.year_max}` : ""}
        {scope.unknown_years ? ` · ${scope.unknown_years} 篇年份未知` : ""}
      </span>
    </div>
  );
}