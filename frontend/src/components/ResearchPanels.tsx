import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  GitBranch,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, copyText } from "../lib/api";
import type {
  Citation,
  ConflictResult,
  EvolutionResult,
  FacetCell,
  GapValidation,
  MatrixResult,
} from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, Input, Select } from "./ui";

/* ------------------------------------------------------------------ matrix */

export function MatrixView({ data, onOpen }: { data: MatrixResult; onOpen: (paperId: string, page?: number, chunkId?: string) => void }) {
  const { toast } = useApp();
  const [year, setYear] = useState("all");
  const [method, setMethod] = useState("all");
  const [paperId, setPaperId] = useState("all");
  const [onlyVerified, setOnlyVerified] = useState(false);
  const [query, setQuery] = useState("");

  const years = useMemo(
    () => Array.from(new Set(data.rows.map((row) => row.year).filter(Boolean))).sort() as number[],
    [data.rows],
  );
  const methods = useMemo(
    () => Array.from(new Set(data.rows.map((row) => row.fields.method?.text).filter(Boolean))) as string[],
    [data.rows],
  );

  const rows = data.rows.filter((row) => {
    if (year !== "all" && String(row.year || "") !== year) return false;
    if (paperId !== "all" && row.paper_id !== paperId) return false;
    if (method !== "all" && row.fields.method?.text !== method) return false;
    if (onlyVerified && !Object.values(row.fields).some((cell) => cell.verified)) return false;
    if (query.trim()) {
      const needle = query.trim().toLowerCase();
      const haystack = Object.values(row.fields).map((cell) => cell.text).join(" ") + " " + row.title;
      if (!haystack.toLowerCase().includes(needle)) return false;
    }
    return true;
  });

  async function copyMatrix() {
    const header = ["论文", ...data.dimensions.map((dimension) => dimension.label)];
    const lines = [header.join(" | "), header.map(() => "---").join(" | ")];
    for (const row of rows) {
      lines.push(
        [row.title, ...data.dimensions.map((dimension) => (row.fields[dimension.id]?.text || "未提及").replace(/\|/g, "/"))].join(" | "),
      );
    }
    const ok = await copyText(lines.join("\n"));
    toast(ok ? "矩阵已复制为 Markdown" : "复制失败", ok ? "success" : "error");
  }

  return (
    <Card className="p4-panel">
      <div className="p4-head">
        <div>
          <h2>研究证据矩阵</h2>
          <p>{data.scope} · {data.local ? "本地抽取" : "模型提取 + 原文核验"}</p>
        </div>
        <div className="p4-head-actions">
          <Badge tone={data.local ? "warn" : "accent"}>{data.local ? "本地模式" : "生成式"}</Badge>
          <Button size="sm" variant="ghost" icon={<Copy size={13} />} onClick={() => void copyMatrix()}>复制</Button>
        </div>
      </div>
      <p className="p4-note">{data.note}</p>

      <div className="p4-filters">
        <div className="p4-search">
          <Search size={14} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索问题、方法、结论" />
        </div>
        <Select value={paperId} onChange={(event) => setPaperId(event.target.value)} aria-label="按论文筛选">
          <option value="all">全部论文</option>
          {data.rows.map((row) => <option key={row.paper_id} value={row.paper_id}>{truncate(row.title, 34)}</option>)}
        </Select>
        <Select value={year} onChange={(event) => setYear(event.target.value)} aria-label="按年份筛选">
          <option value="all">全部年份</option>
          {years.map((item) => <option key={item} value={item}>{item}</option>)}
        </Select>
        <Select value={method} onChange={(event) => setMethod(event.target.value)} aria-label="按方法筛选">
          <option value="all">全部方法</option>
          {methods.map((item) => <option key={item} value={item}>{truncate(item, 28)}</option>)}
        </Select>
        <label className="p4-check">
          <input type="checkbox" checked={onlyVerified} onChange={(event) => setOnlyVerified(event.target.checked)} />
          仅看有已核对证据
        </label>
      </div>

      <div className="matrix-scroll">
        <table className="matrix-table">
          <thead>
            <tr>
              <th className="matrix-paper-col">论文</th>
              {data.dimensions.map((dimension) => <th key={dimension.id}>{dimension.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.paper_id}>
                <td className="matrix-paper-col">
                  <button onClick={() => onOpen(row.paper_id)}>{truncate(row.title, 48)}</button>
                  <span>{row.year || "年份未知"}</span>
                </td>
                {data.dimensions.map((dimension) => (
                  <td key={dimension.id}>
                    <MatrixCell cell={row.fields[dimension.id]} onOpen={(page, chunk) => onOpen(row.paper_id, page, chunk)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="p4-empty">没有符合筛选条件的论文。</p>}
    </Card>
  );
}

function MatrixCell({ cell, onOpen }: { cell?: FacetCell; onOpen: (page?: number, chunkId?: string) => void }) {
  if (!cell || !cell.text || cell.text === "未提及") {
    return <span className="matrix-empty">未提及</span>;
  }
  return (
    <div className="matrix-cell">
      <span>{truncate(cell.text, 120)}</span>
      <div className="matrix-cell-foot">
        {cell.page && (
          <button onClick={() => onOpen(cell.page ?? undefined, cell.chunk_id ?? undefined)}>
            p.{cell.page} <ExternalLink size={10} />
          </button>
        )}
        {cell.verified ? (
          <span className="matrix-verified"><CheckCircle2 size={10} /> 已核对</span>
        ) : (
          <span className="matrix-unverified"><AlertTriangle size={10} /> 未核对</span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ conflicts */

export function ConflictView({ data, onOpen }: { data: ConflictResult; onOpen: (paperId: string, page?: number) => void }) {
  return (
    <Card className="p4-panel">
      <div className="p4-head">
        <div>
          <h2>学术观点冲突</h2>
          <p>{data.scope} · {data.conflicts.length} 组冲突 · {data.local ? "本地证据并列" : "生成式判断 + 证据"}</p>
        </div>
        <Badge tone={data.local ? "warn" : "accent"}>{data.local ? "本地模式" : "生成式"}</Badge>
      </div>
      <p className="p4-note">{data.note}</p>

      {data.conflicts.length > 0 && (
        <div className="conflict-list">
          {data.conflicts.map((conflict, index) => (
            <article key={index} className="conflict-card">
              <div className="conflict-head">
                <Badge tone={conflict.comparable ? "accent" : "warn"}>
                  {conflict.comparable ? "条件可比" : "条件不同，不可直接比较"}
                </Badge>
                <Badge tone={conflict.severity === "high" ? "danger" : conflict.severity === "low" ? "neutral" : "warn"}>
                  {conflict.severity}
                </Badge>
                <strong>{conflict.question}</strong>
              </div>
              <div className="conflict-stances">
                <div>
                  <span>观点 A</span>
                  <p>{conflict.stance_a}</p>
                  <button onClick={() => onOpen(conflict.paper_a)}>来源论文 <ArrowRight size={11} /></button>
                </div>
                <div>
                  <span>观点 B</span>
                  <p>{conflict.stance_b}</p>
                  <button onClick={() => onOpen(conflict.paper_b)}>来源论文 <ArrowRight size={11} /></button>
                </div>
              </div>
              {conflict.analysis && <p className="conflict-analysis">{conflict.analysis}</p>}
              {conflict.evidence.length > 0 && (
                <div className="conflict-evidence">
                  {conflict.evidence.slice(0, 4).map((citation) => (
                    <button key={citation.key + citation.chunk_id} onClick={() => onOpen(citation.paper_id || "", citation.page)}>
                      <span>{citation.key}</span> p.{citation.page} · {truncate(citation.quote, 80)}
                    </button>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      <div className="comparability-block">
        <h3>实验条件与可比性</h3>
        {data.comparability.map((pair) => (
          <div key={pair.paper_a + pair.paper_b} className={cn("comparability-card", pair.comparable ? "comparable" : "not-comparable")}>
            <div className="comparability-head">
              <span>{truncate(pair.title_a, 30)}</span>
              <ArrowRight size={12} />
              <span>{truncate(pair.title_b, 30)}</span>
              <Badge tone={pair.comparable ? "accent" : "warn"}>{pair.comparable ? "可比" : "不可直接比较"}</Badge>
            </div>
            <div className="comparability-grid">
              <div><span>数据集 A</span><p>{pair.dataset_a}</p></div>
              <div><span>数据集 B</span><p>{pair.dataset_b}</p></div>
              <div><span>指标 A</span><p>{pair.metrics_a}</p></div>
              <div><span>指标 B</span><p>{pair.metrics_b}</p></div>
            </div>
            <p className="comparability-reason">{pair.reason}</p>
          </div>
        ))}
      </div>

      {data.local && (
        <div className="profile-compare">
          <h3>并列研究画像（非冲突判定）</h3>
          <div className="profile-grid">
            {data.profiles.map((profile) => (
              <div key={profile.paper_id} className="profile-card">
                <strong>{truncate(profile.title, 50)}</strong>
                <span>{profile.year || "年份未知"}</span>
                <p><em>方法</em>{profile.method}</p>
                <p><em>发现</em>{profile.findings}</p>
                <p><em>局限</em>{profile.limits}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ evolution */

export function EvolutionView({ data, onOpen }: { data: EvolutionResult; onOpen: (paperId: string, page?: number) => void }) {
  const grouped = data.timeline.reduce<Record<string, typeof data.timeline>>((acc, item) => {
    const key = item.year ? String(item.year) : "年份未知";
    acc[key] = acc[key] || [];
    acc[key].push(item);
    return acc;
  }, {});
  const orderedYears = Object.keys(grouped).sort((a, b) => {
    if (a === "年份未知") return 1;
    if (b === "年份未知") return -1;
    return Number(a) - Number(b);
  });

  return (
    <Card className="p4-panel">
      <div className="p4-head">
        <div>
          <h2>研究方法演化</h2>
          <p>{data.scope} · {data.relations.length} 条关系</p>
        </div>
        <Badge tone={data.local ? "warn" : "accent"}>{data.local ? "本地时间线" : "生成式 + 证据"}</Badge>
      </div>
      <p className="p4-note">{data.note}</p>

      <div className="evolution-layout">
        <div className="evo-timeline">
          {orderedYears.map((year) => (
            <div key={year} className="evo-year">
              <span className="evo-year-label">{year}</span>
              <div className="evo-year-items">
                {grouped[year].map((item) => (
                  <button key={item.paper_id} className="evo-paper" onClick={() => onOpen(item.paper_id)}>
                    <strong>{truncate(item.title, 54)}</strong>
                    <p><em>方法</em>{item.method}</p>
                    <p><em>发现</em>{truncate(item.findings, 100)}</p>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <aside className="evolution-relations">
          <h3><GitBranch size={14} /> 方法关系</h3>
          {data.relations.length === 0 ? (
            <div className="p4-empty-box">
              <ShieldCheck size={18} />
              <p>{data.local ? "本地模式不推断继承关系。仅按真实年份排列方法，避免把时间先后误认为技术演化。" : "本次分析没有找到有证据支持的方法关系。"}</p>
            </div>
          ) : (
            data.relations.map((relation, index) => (
              <div key={index} className={cn("relation-card", relation.status)}>
                <div className="relation-head">
                  <Badge tone={relation.status === "explicit" ? "accent" : relation.status === "possible" ? "warn" : "neutral"}>
                    {relation.status === "explicit" ? "原文明确" : relation.status === "possible" ? "可能" : "未知"}
                  </Badge>
                  <span>{relation.relation}</span>
                </div>
                <p>{relation.reason}</p>
                {relation.evidence.slice(0, 2).map((citation) => (
                  <button key={citation.key} onClick={() => onOpen(citation.paper_id || "", citation.page)}>
                    {citation.key} · p.{citation.page}
                  </button>
                ))}
              </div>
            ))
          )}
        </aside>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ gap validation */

export function GapValidationPanel({
  paperIds,
  onOpen,
}: {
  paperIds: string[];
  onOpen: (paperId: string, page?: number) => void;
}) {
  const { toast } = useApp();
  const [claim, setClaim] = useState("");
  const [result, setResult] = useState<GapValidation | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    const value = claim.trim();
    if (!value) {
      toast("请输入要验证的研究缺口", "error");
      return;
    }
    if (paperIds.length < 1) {
      toast("请先选择论文", "error");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const response = await api<GapValidation>("/research/gap/validate", {
        method: "POST",
        body: { claim: value, paper_ids: paperIds },
      });
      setResult(response);
    } catch (error) {
      toast((error as Error).message || "验证失败", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="gap-validation">
      <div className="gap-validation-head">
        <div>
          <h3>跨论文验证一个研究缺口</h3>
          <p>检索资料库，看看有多少篇论文包含与该缺口相关的原文证据。</p>
        </div>
        <ShieldCheck size={18} />
      </div>
      <div className="gap-validation-input">
        <Input
          value={claim}
          onChange={(event) => setClaim(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void run()}
          placeholder="例如：现有方法在低资源语言上的评估仍不充分"
        />
        <Button size="sm" variant="primary" loading={loading} onClick={() => void run()}>
          验证
        </Button>
      </div>
      {result && (
        <div className="gap-validation-result">
          <div className="gap-validation-stats">
            <span><strong>{result.support_count}</strong> / {result.paper_count} 篇论文有相关证据</span>
            <Badge tone={result.strength === "multi" ? "accent" : result.strength === "single" ? "warn" : "neutral"}>
              {result.strength === "multi" ? "多篇覆盖" : result.strength === "single" ? "单篇覆盖" : "未覆盖"}
            </Badge>
          </div>
          {result.supports.map((support) => (
            <button key={support.paper_id} className="gap-support" onClick={() => onOpen(support.paper_id, support.page)}>
              <strong>{truncate(support.paper_title, 46)}</strong>
              <span>p.{support.page} · {support.section}</span>
              <p>{truncate(support.quote, 180)}</p>
            </button>
          ))}
          <p className="p4-note">{result.note}</p>
        </div>
      )}
    </Card>
  );
}

export function evidenceCount(citations: Citation[]): number {
  return citations.length;
}