import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpenCheck,
  FolderKanban,
  Layers,
  Radar,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type {
  Collection,
  ConflictResult,
  EvolutionResult,
  IntelligenceOverview,
  IntelligenceScope,
  MatrixResult,
  Paper,
  Project,
} from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, EmptyState, Select, Spinner, Tabs } from "../components/ui";
import {
  ConnectionsView,
  LandscapeView,
  OpportunitiesView,
  ScopeBoundary,
  TrendsView,
} from "../components/IntelligenceViews";
import { ConflictView, EvolutionView, MatrixView } from "../components/ResearchPanels";

type IntelligenceTab = "landscape" | "trends" | "connections" | "opportunities" | "matrix" | "conflicts" | "evolution";

const TABS = [
  { id: "landscape", label: "研究全景" },
  { id: "trends", label: "研究趋势" },
  { id: "connections", label: "知识关联" },
  { id: "opportunities", label: "研究机会" },
  { id: "matrix", label: "证据矩阵" },
  { id: "conflicts", label: "观点冲突" },
  { id: "evolution", label: "方法演化" },
];

export function Intelligence() {
  const { toast, model } = useApp();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [scopeType, setScopeType] = useState("all");
  const [scopeId, setScopeId] = useState("");
  const [scope, setScope] = useState<IntelligenceScope | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loadingScope, setLoadingScope] = useState(true);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [overview, setOverview] = useState<IntelligenceOverview | null>(null);
  const [generating, setGenerating] = useState(false);
  const [tab, setTab] = useState<IntelligenceTab>("landscape");
  const [matrix, setMatrix] = useState<MatrixResult | null>(null);
  const [conflicts, setConflicts] = useState<ConflictResult | null>(null);
  const [evolution, setEvolution] = useState<EvolutionResult | null>(null);
  const [p4Loading, setP4Loading] = useState(false);

  useEffect(() => {
    void Promise.all([
      api<{ items: Project[] }>("/projects"),
      api<{ items: Collection[] }>("/collections"),
    ]).then(([projectResponse, collectionResponse]) => {
      setProjects(projectResponse.items);
      setCollections(collectionResponse.items);
    }).catch(() => undefined);
  }, []);

  const loadScope = useCallback(async () => {
    setLoadingScope(true);
    setScopeError(null);
    try {
      const params = new URLSearchParams({ scope_type: scopeType });
      if (scopeId) params.set("scope_id", scopeId);
      const response = await api<{ scope: IntelligenceScope; papers: Paper[] }>("/intelligence/scope?" + params.toString());
      setScope(response.scope);
      setPapers(response.papers);
    } catch (error) {
      setScope(null);
      setPapers([]);
      setScopeError((error as Error).message || "无法解析研究范围");
    } finally {
      setLoadingScope(false);
    }
  }, [scopeType, scopeId]);

  useEffect(() => {
    setOverview(null);
    setMatrix(null);
    setConflicts(null);
    setEvolution(null);
    setTab("landscape");
    void loadScope();
  }, [loadScope]);

  const scopeValue = scopeType === "all" ? "all" : scopeType + ":" + scopeId;
  const hasScope = Boolean(scope && scope.paper_count > 0);

  async function generate(force = true) {
    if (!hasScope) return;
    setGenerating(true);
    try {
      const response = await api<IntelligenceOverview>("/intelligence/overview", {
        method: "POST",
        body: { scope_type: scopeType, scope_id: scopeId || null, force },
      });
      setOverview(response);
      setScope(response.scope);
      toast("研究情报已生成", "success");
    } catch (error) {
      toast((error as Error).message || "生成失败", "error");
    } finally {
      setGenerating(false);
    }
  }

  async function loadP4(kind: "matrix" | "conflicts" | "evolution") {
    if (papers.length === 0 || p4Loading) return;
    if ((kind === "conflicts" || kind === "evolution") && papers.length < 2) {
      toast("该分析至少需要两篇论文", "info");
      return;
    }
    setP4Loading(true);
    try {
      const body = { paper_ids: papers.slice(0, 8).map((paper) => paper.id) };
      if (kind === "matrix") {
        setMatrix(await api<MatrixResult>("/research/matrix", { method: "POST", body }));
      } else if (kind === "conflicts") {
        setConflicts(await api<ConflictResult>("/research/conflicts", { method: "POST", body }));
      } else {
        setEvolution(await api<EvolutionResult>("/research/evolution", { method: "POST", body }));
      }
    } catch (error) {
      toast((error as Error).message || "分析失败", "error");
    } finally {
      setP4Loading(false);
    }
  }

  useEffect(() => {
    if (!overview) return;
    if (tab === "matrix" && !matrix) void loadP4("matrix");
    if (tab === "conflicts" && !conflicts) void loadP4("conflicts");
    if (tab === "evolution" && !evolution) void loadP4("evolution");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, overview]);

  function openPaper(paperId: string, page?: number) {
    const params = new URLSearchParams();
    if (page) params.set("page", String(page));
    navigate("/app/papers/" + paperId + (params.toString() ? "?" + params.toString() : ""));
  }

  const scopeOptions = useMemo(
    () => [
      { value: "all", label: "全部资料库" },
      ...projects.map((project) => ({ value: "project:" + project.id, label: "项目 · " + project.name })),
      ...collections.map((collection) => ({ value: "collection:" + collection.id, label: "合集 · " + collection.name })),
    ],
    [projects, collections],
  );

  return (
    <div className="page page-intelligence">
      <header className="page-head">
        <div>
          <span className="eyebrow"><Radar size={12} /> Research Intelligence</span>
          <h1>研究情报中心</h1>
          <p>基于你的资料库建立领域认知：全景、趋势、知识关联与研究机会。所有判断标注范围与证据。</p>
        </div>
        <Badge tone={model?.configured ? "accent" : "warn"}>{model?.configured ? "生成式模式" : "本地抽取模式"}</Badge>
      </header>

      <Card className="intel-scope-bar">
        <div className="intel-scope-left">
          <span className="intel-scope-label">研究范围</span>
          <Select
            value={scopeValue}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "all") {
                setScopeType("all");
                setScopeId("");
              } else {
                const [type, id] = value.split(":");
                setScopeType(type);
                setScopeId(id);
              }
            }}
          >
            {scopeOptions.map((option) => <option key={option.value} value={option.value}>{truncate(option.label, 48)}</option>)}
          </Select>
          {scope && (
            <span className="intel-scope-meta">
              {scope.paper_count} 篇 · {scope.year_min || "未知"}–{scope.year_max || "未知"}
            </span>
          )}
        </div>
        <div className="intel-scope-actions">
          <Button
            variant="primary"
            icon={<Sparkles size={15} />}
            loading={generating}
            disabled={!hasScope}
            onClick={() => void generate(true)}
          >
            {overview ? "重新生成" : "生成研究情报"}
          </Button>
        </div>
      </Card>

      {scope && <ScopeBoundary scope={scope} />}

      {loadingScope ? (
        <Card className="intel-loading"><Spinner size={18} /> 正在解析研究范围…</Card>
      ) : scopeError || !hasScope ? (
        <EmptyState
          icon={<BookOpenCheck size={26} />}
          title={scopeError || "该范围内没有已解析的论文"}
          description="研究情报只能基于真实论文生成。请先上传并解析论文，或切换到有论文的项目/合集。"
          action={<Button variant="primary" onClick={() => navigate("/app/papers")}>前往论文库</Button>}
        />
      ) : !overview ? (
        <Card className="intel-generate">
          <div className="intel-generate-icon"><Radar size={26} /></div>
          <h2>把资料库变成研究情报</h2>
          <p>
            PaperLens 会先为每篇论文建立六维证据画像，再生成资料库范围内的研究全景、趋势、知识关联与研究机会。
            没有外部学术数据时，不会声称这是全球领域结论。
          </p>
          <div className="intel-generate-points">
            <span><Layers size={14} /> 证据矩阵 / 观点冲突 / 方法演化</span>
            <span><FolderKanban size={14} /> 可按项目或合集独立分析</span>
            <span><Radar size={14} /> 结果会标注本地/生成式模式</span>
          </div>
          <Button variant="primary" size="lg" icon={<Sparkles size={16} />} loading={generating} onClick={() => void generate(true)}>
            生成本范围研究情报
          </Button>
        </Card>
      ) : (
        <>
          <div className="intel-tabs-row">
            <Tabs
              items={TABS}
              value={tab}
              onChange={(next) => setTab(next as IntelligenceTab)}
            />
            <Button size="sm" variant="ghost" icon={<RefreshCw size={13} />} loading={generating} onClick={() => void generate(true)}>
              刷新
            </Button>
          </div>

          {tab === "landscape" && <LandscapeView data={overview.reports.landscape.data} onOpen={openPaper} />}
          {tab === "trends" && <TrendsView data={overview.reports.trends.data} onOpen={openPaper} />}
          {tab === "connections" && <ConnectionsView data={overview.reports.connections.data} onOpen={openPaper} />}
          {tab === "opportunities" && <OpportunitiesView data={overview.reports.opportunities.data} onOpen={openPaper} />}

          {tab === "matrix" && (matrix ? <MatrixView data={matrix} onOpen={openPaper} /> : <P4Loading loading={p4Loading} label="证据矩阵" />)}
          {tab === "conflicts" && (conflicts ? <ConflictView data={conflicts} onOpen={openPaper} /> : <P4Loading loading={p4Loading} label="观点冲突" />)}
          {tab === "evolution" && (evolution ? <EvolutionView data={evolution} onOpen={openPaper} /> : <P4Loading loading={p4Loading} label="方法演化" />)}
        </>
      )}
    </div>
  );
}

function P4Loading({ loading, label }: { loading: boolean; label: string }) {
  return (
    <Card className="intel-loading">
      {loading ? <Spinner size={18} /> : null}
      {loading ? "正在生成" + label + "…" : "暂无" + label + "结果，请刷新研究情报。"}
    </Card>
  );
}
