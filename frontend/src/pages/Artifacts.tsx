import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  ChevronDown,
  Download,
  FileCheck2,
  FileText,
  Loader2,
  Save,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, downloadFile } from "../lib/api";
import type {
  AcademicArtifact,
  ArtifactKind,
  ArtifactPreflight,
  ArtifactQuality,
  Collection,
  Paper,
  Project,
} from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, EmptyState, Select, Spinner } from "../components/ui";
import { MarkdownView } from "../components/Markdown";

export function Artifacts() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [kinds, setKinds] = useState<ArtifactKind[]>([]);
  const [artifacts, setArtifacts] = useState<AcademicArtifact[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [artifact, setArtifact] = useState<AcademicArtifact | null>(null);
  const [quality, setQuality] = useState<ArtifactQuality | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState("");
  const [preflight, setPreflight] = useState<ArtifactPreflight | null>(null);
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [scopeType, setScopeType] = useState("all");
  const [scopeId, setScopeId] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [searchParams] = useSearchParams();

  const loadArtifacts = useCallback(async () => {
    try {
      const response = await api<{ items: AcademicArtifact[] }>("/artifacts?limit=50");
      setArtifacts(response.items);
      return response.items;
    } catch (error) {
      toast((error as Error).message || "无法加载成果", "error");
      return [];
    }
  }, [toast]);

  useEffect(() => {
    void Promise.all([
      api<{ items: ArtifactKind[] }>("/artifacts/kinds"),
      api<{ items: Project[] }>("/projects"),
      api<{ items: Collection[] }>("/collections"),
      api<{ items: Paper[] }>("/papers?limit=100"),
    ]).then(([kindResponse, projectResponse, collectionResponse, paperResponse]) => {
      setKinds(kindResponse.items);
      setProjects(projectResponse.items);
      setCollections(collectionResponse.items);
      setPapers(paperResponse.items);
      const firstReady = paperResponse.items.find((paper) => paper.status === "ready");
      if (firstReady) setSelectedPaperId(firstReady.id);
    }).catch(() => undefined);
    void loadArtifacts().then((items) => {
      if (items.length > 0) setSelectedId((current) => current || items[0].id);
    }).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      const response = await api<{ artifact: AcademicArtifact; quality: ArtifactQuality | null }>("/artifacts/" + id);
      setArtifact(response.artifact);
      setQuality(response.quality);
    } catch (error) {
      toast((error as Error).message || "无法加载成果详情", "error");
      setArtifact(null);
      setQuality(null);
    }
  }, [toast]);

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (focus && focus !== selectedId) setSelectedId(focus);
  }, [searchParams]);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!selectedPaperId) {
      setPreflight(null);
      return;
    }
    let active = true;
    api<{ preflight: ArtifactPreflight }>("/artifacts/preflight?paper_id=" + selectedPaperId)
      .then((response) => { if (active) setPreflight(response.preflight); })
      .catch(() => { if (active) setPreflight(null); });
    return () => { active = false; };
  }, [selectedPaperId]);

  async function generate(kind: string, bodyOverride?: Record<string, unknown>) {
    setGenerating(kind);
    try {
      const response = await api<{ artifact: AcademicArtifact; quality: ArtifactQuality }>("/artifacts/generate", {
        method: "POST",
        body: bodyOverride || { kind, scope_type: scopeType, scope_id: scopeId || null },
      });
      setArtifact(response.artifact);
      setQuality(response.quality);
      setSelectedId(response.artifact.id);
      await loadArtifacts();
      if (response.quality?.status === "fail") {
        toast("已生成草稿，但质检未通过；请查看下方问题", "error");
      } else if (response.quality?.status === "warning") {
        toast("知识内容已生成，存在需要人工核对的风险", "info");
      } else {
        toast("内容已生成并通过质检", "success");
      }
      return response.artifact;
    } catch (error) {
      toast((error as Error).message || "生成失败", "error");
      return null;
    } finally {
      setGenerating(null);
    }
  }

  async function generateKnowledgePack() {
    if (!selectedPaperId) {
      toast("请先选择一篇论文", "info");
      return;
    }
    // Clear the old advanced draft so a failed pack generation cannot be
    // mistaken for a knowledge pack bound to the whole library.
    setArtifact(null);
    setQuality(null);
    const result = await generate("knowledge_pack", {
      kind: "knowledge_pack",
      scope_type: "papers",
      paper_ids: [selectedPaperId],
    });
    if (result) {
      setSelectedId(result.id);
    }
  }

  async function regenerateArtifact() {
    if (!artifact) return;
    await generate(artifact.kind, {
      kind: artifact.kind,
      scope_type: artifact.scope_type === "papers" ? "papers" : artifact.scope_type,
      scope_id: artifact.scope_type === "papers" ? null : (artifact.scope_ids?.[0] || null),
      paper_ids: artifact.paper_ids || [],
    });
  }

  async function saveToKnowledge() {
    if (!artifact || artifact.kind !== "knowledge_pack") return;
    setSavingKnowledge(true);
    try {
      const response = await api<{ artifact: AcademicArtifact; count: number }>("/artifacts/" + artifact.id + "/save-to-knowledge", { method: "POST" });
      setArtifact(response.artifact);
      await loadArtifacts();
      toast("已存入知识库 " + response.count + " 条", "success");
    } catch (error) {
      toast((error as Error).message || "保存到知识库失败", "error");
    } finally {
      setSavingKnowledge(false);
    }
  }

  async function recheck() {
    if (!artifact) return;
    setChecking(true);
    try {
      const response = await api<{ quality: ArtifactQuality; artifact: AcademicArtifact }>("/artifacts/" + artifact.id + "/check", { method: "POST" });
      setQuality(response.quality);
      setArtifact(response.artifact);
      toast("质检已更新", "success");
    } catch (error) {
      toast((error as Error).message || "质检失败", "error");
    } finally {
      setChecking(false);
    }
  }

  async function exportArtifact(fmt: string) {
    if (!artifact) return;
    setExporting(fmt);
    try {
      const response = await api<{ export: { download_url: string; filename: string } }>("/artifacts/" + artifact.id + "/export", {
        method: "POST",
        body: { format: fmt },
      });
      await downloadFile(response.export.download_url, response.export.filename);
      toast("已导出 " + fmt.toUpperCase(), "success");
    } catch (error) {
      toast((error as Error).message || "导出失败", "error");
    } finally {
      setExporting(null);
    }
  }

  const scopeOptions = useMemo(
    () => [
      { value: "all", label: "全部资料库" },
      ...projects.map((project) => ({ value: "project:" + project.id, label: "项目 · " + project.name })),
      ...collections.map((collection) => ({ value: "collection:" + collection.id, label: "合集 · " + collection.name })),
    ],
    [projects, collections],
  );

  const qualityTone = quality?.status === "pass" ? "accent" : quality?.status === "fail" ? "danger" : "warn";
  const builderPack = artifact?.kind === "knowledge_pack" && selectedPaperId && (artifact.paper_ids || []).includes(selectedPaperId) ? artifact : null;

  return (
    <div className="page page-artifacts">
      <header className="page-head">
        <div>
          <span className="eyebrow"><ScrollText size={12} /> Paper knowledge</span>
          <h1>论文知识包</h1>
          <p>选一篇论文，生成可追溯知识包并存入知识库。</p>
        </div>
        <Badge tone="accent">本地确定性生成</Badge>
      </header>

      <Card className="artifact-builder">
        <div className="artifact-builder-row">
          <div className="artifact-builder-scope">
            <span className="artifact-scope-label">目标论文</span>
            <Select value={selectedPaperId} onChange={(event) => setSelectedPaperId(event.target.value)}>
              <option value="">选择一篇论文</option>
              {papers.map((paper) => (
                <option key={paper.id} value={paper.id}>{truncate(paper.title, 68)}{paper.year ? " · " + paper.year : ""}</option>
              ))}
            </Select>
          </div>
          <div className={cn("artifact-preflight-inline", preflight?.ready ? "ready" : "blocked")}>
            <strong>{preflight ? (preflight.ready ? "可生成" : "不可生成") : "等待选择"}</strong>
            {preflight?.ready ? (
              <span>{preflight.pages} 页 · {preflight.chunks} 片段</span>
            ) : (
              <span>{preflight?.message || "先选择一篇已解析论文"}</span>
            )}
          </div>
        </div>

        <p className="artifact-builder-summary">生成：论文速览、研究问题、方法与数据、主要发现、局限、知识卡、证据表</p>

        <div className="artifact-builder-actions">
          <Button
            variant="primary"
            loading={generating === "knowledge_pack"}
            disabled={!preflight?.ready}
            onClick={() => void generateKnowledgePack()}
          >
            生成知识包
          </Button>
          {builderPack && (
            <Button
              variant={builderPack.knowledge_saved ? "soft" : "secondary"}
              icon={<Save size={14} />}
              loading={savingKnowledge}
              disabled={builderPack.knowledge_saved}
              onClick={() => void saveToKnowledge()}
            >
              {builderPack.knowledge_saved ? "已存入知识库" : "保存到知识库"}
            </Button>
          )}
          <Button variant="ghost" icon={<ScrollText size={14} />} onClick={() => navigate("/app/knowledge")}>
            查看知识库
          </Button>
        </div>
      </Card>

      <details className="artifact-advanced" open>
        <summary>
          <span><FileText size={14} /> 高级写作草稿</span>
          <small>多论文文献综述、开题、实验设计、PPT 大纲</small>
          <ChevronDown size={15} />
        </summary>
        <Card className="artifact-scope">
          <div>
            <span className="artifact-scope-label">研究范围</span>
            <Select
              value={scopeType === "all" ? "all" : scopeType + ":" + scopeId}
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
              {scopeOptions.map((option) => <option key={option.value} value={option.value}>{truncate(option.label, 50)}</option>)}
            </Select>
            <span className="muted small">只使用资料库内论文；不引入外部文献。扫描件会被自动排除。</span>
          </div>
        </Card>
        <div className="artifact-kinds">
          {kinds.filter((kind) => kind.id !== "knowledge_pack").map((kind) => (
            <Card key={kind.id} className={cn("artifact-kind-card", generating === kind.id && "generating")}>
              <div className="artifact-kind-icon"><FileText size={16} /></div>
              <strong>{kind.label}</strong>
              <p>{kind.description}</p>
              <Button
                size="sm"
                variant="secondary"
                loading={generating === kind.id}
                disabled={Boolean(generating) && generating !== kind.id}
                onClick={() => void generate(kind.id)}
              >
                生成
              </Button>
            </Card>
          ))}
        </div>
      </details>

      <div className="artifact-layout">
        <Card className="artifact-history">
          <div className="artifact-section-head">
            <h3><ScrollText size={14} /> 历史成果</h3>
            <span>{artifacts.length}</span>
          </div>
          {loading ? <div className="artifact-loading"><Spinner size={14} /> 加载…</div> : artifacts.length === 0 ? (
            <p className="muted small">还没有成果。选择上方类型生成第一份。</p>
          ) : (
            <div className="artifact-history-list">
              {artifacts.map((item) => (
                <button key={item.id} className={cn("artifact-history-item", selectedId === item.id && "active")} onClick={() => setSelectedId(item.id)}>
                  <div>
                    <strong>{truncate(item.title, 48)}</strong>
                    <span>{kinds.find((kind) => kind.id === item.kind)?.label || item.kind} · {formatDate(item.created_at)}</span>
                  </div>
                  <Badge tone={item.quality_status === "pass" ? "accent" : item.quality_status === "fail" ? "danger" : "warn"}>
                    {item.quality_score}
                  </Badge>
                </button>
              ))}
            </div>
          )}
        </Card>

        <div className="artifact-main">
          {!artifact ? (
            <EmptyState icon={<FileCheck2 size={28} />} title="选择论文生成知识包" description="在上方选择论文，一键生成摘要、问题、方法、发现、局限与可引用证据，并保存到知识库。" />
          ) : (
            <>
              <Card className="artifact-preview">
                <div className="artifact-preview-head">
                  <div>
                    <span className="eyebrow">{kinds.find((kind) => kind.id === artifact.kind)?.label || artifact.kind}</span>
                    <h2>{artifact.title}</h2>
                    <p>{artifact.scope_statement}</p>
                  </div>
                  <div className="artifact-actions">
                    {artifact && (
                      <Button size="sm" variant="soft" onClick={() => navigate("/app?artifact=" + encodeURIComponent(artifact.id))}>
                        在 Chat 中使用
                      </Button>
                    )}
                    <Badge tone={qualityTone}>{quality?.status === "pass" ? "质检通过" : quality?.status === "fail" ? "质检失败" : "有风险"}</Badge>
                    <Button size="sm" variant="ghost" icon={<ShieldCheck size={13} />} loading={checking} onClick={() => void recheck()}>重新质检</Button>
                    {quality?.status === "fail" && (
                      <Button size="sm" variant="secondary" loading={generating === artifact.kind} onClick={() => void regenerateArtifact()}>重新生成</Button>
                    )}
                    {artifact.kind === "knowledge_pack" && (
                      <Button size="sm" variant={artifact.knowledge_saved ? "soft" : "secondary"} icon={<Save size={13} />} loading={savingKnowledge} disabled={artifact.knowledge_saved} onClick={() => void saveToKnowledge()}>
                        {artifact.knowledge_saved ? "已存入知识库" : "保存到知识库"}
                      </Button>
                    )}
                  </div>
                </div>
                <div className="artifact-export-row">
                  <span className="muted small">导出</span>
                  {["md", "pdf", "docx"].map((fmt) => (
                    <Button key={fmt} size="sm" variant="ghost" loading={exporting === fmt} icon={<Download size={12} />} onClick={() => void exportArtifact(fmt)}>
                      {fmt.toUpperCase()}
                    </Button>
                  ))}
                </div>
                <MarkdownView content={artifact.content} />
              </Card>

              <Card className="artifact-evidence">
                <div className="artifact-section-head">
                  <h3><FileCheck2 size={14} /> 证据表</h3>
                  <span>{artifact.evidence_table.length} 条</span>
                </div>
                <div className="artifact-evidence-scroll">
                  <table>
                    <thead><tr><th>key</th><th>论文</th><th>页</th><th>原文</th><th>核验</th></tr></thead>
                    <tbody>
                      {artifact.evidence_table.map((row) => (
                        <tr key={row.key}>
                          <td><span className="artifact-key">{row.key}</span></td>
                          <td>{truncate(row.paper_title, 40)}</td>
                          <td>{row.page || "?"}</td>
                          <td>{truncate(row.quote, 130)}</td>
                          <td>{row.verified ? "是" : "否"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card className="artifact-quality">
                <div className="artifact-section-head">
                  <h3><ShieldCheck size={14} /> Quality Checker</h3>
                  <div>
                    <Badge tone={qualityTone}>{quality?.status || "unchecked"}</Badge>
                    <span className="artifact-score">{quality?.score ?? 0}/100</span>
                  </div>
                </div>
                <p className="muted small">{quality?.summary}</p>
                {quality?.status === "fail" && <p className="muted small">该成果可能来自旧解析或旧引用；点击上方“重新生成”会用当前论文重新提取证据。</p>}
                {quality && quality.issues.length > 0 ? (
                  <div className="artifact-issues">
                    {quality.issues.map((issue, index) => (
                      <div key={issue.code + index} className={cn("artifact-issue", issue.severity)}>
                        <span>{issue.severity}</span>
                        <p>{issue.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted small">没有发现问题。</p>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return value;
  }
}