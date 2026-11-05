import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Download,
  FileCheck2,
  FileText,
  Loader2,
  RefreshCw,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, downloadFile } from "../lib/api";
import type {
  AcademicArtifact,
  ArtifactKind,
  ArtifactQuality,
  Collection,
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
  const [scopeType, setScopeType] = useState("all");
  const [scopeId, setScopeId] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);

  const loadArtifacts = useCallback(async () => {
    try {
      const response = await api<{ items: AcademicArtifact[] }>("/artifacts?limit=50");
      setArtifacts(response.items);
      if (!selectedId && response.items.length > 0) setSelectedId(response.items[0].id);
    } catch (error) {
      toast((error as Error).message || "无法加载成果", "error");
    }
  }, [selectedId, toast]);

  useEffect(() => {
    void Promise.all([
      api<{ items: ArtifactKind[] }>("/artifacts/kinds"),
      api<{ items: Project[] }>("/projects"),
      api<{ items: Collection[] }>("/collections"),
    ]).then(([kindResponse, projectResponse, collectionResponse]) => {
      setKinds(kindResponse.items);
      setProjects(projectResponse.items);
      setCollections(collectionResponse.items);
    }).catch(() => undefined);
    void loadArtifacts().finally(() => setLoading(false));
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
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  async function generate(kind: string) {
    setGenerating(kind);
    try {
      const response = await api<{ artifact: AcademicArtifact; quality: ArtifactQuality }>("/artifacts/generate", {
        method: "POST",
        body: { kind, scope_type: scopeType, scope_id: scopeId || null },
      });
      setArtifact(response.artifact);
      setQuality(response.quality);
      setSelectedId(response.artifact.id);
      await loadArtifacts();
      toast("成果已生成并完成质检", "success");
    } catch (error) {
      toast((error as Error).message || "生成失败", "error");
    } finally {
      setGenerating(null);
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

  return (
    <div className="page page-artifacts">
      <header className="page-head">
        <div>
          <span className="eyebrow"><ScrollText size={12} /> Academic artifacts</span>
          <h1>学术成果工作台</h1>
          <p>从资料库生成八类带证据的学术初稿；每一份都经过引用、quote、格式与重复检查。</p>
        </div>
        <Badge tone="accent">本地确定性生成</Badge>
      </header>

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
          <span className="muted small">只使用资料库内论文；不引入外部文献。</span>
        </div>
        <Button variant="ghost" icon={<RefreshCw size={14} />} onClick={() => { void loadArtifacts(); if (selectedId) void loadDetail(selectedId); }}>
          刷新
        </Button>
      </Card>

      <div className="artifact-kinds">
        {kinds.map((kind) => (
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
            <EmptyState icon={<FileCheck2 size={28} />} title="选择一种成果生成" description="八类成果都带范围声明与证据表；本地模式不使用外部文献。" />
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
                    <Badge tone={qualityTone}>{quality?.status === "pass" ? "质检通过" : quality?.status === "fail" ? "质检失败" : "有风险"}</Badge>
                    <Button size="sm" variant="ghost" icon={<ShieldCheck size={13} />} loading={checking} onClick={() => void recheck()}>重新质检</Button>
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
