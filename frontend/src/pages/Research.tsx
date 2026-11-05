import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookmarkPlus,
  Check,
  Download,
  FileText,
  Layers,
  Loader2,
  Plus,
  Quote,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { useEvidence } from "../store/EvidenceContext";
import { api, downloadFile } from "../lib/api";
import type { Citation, Collection, ConflictResult, EvolutionResult, MatrixResult, OutlineChunk, Paper } from "../lib/types";
import { ConflictView, EvolutionView, GapValidationPanel, MatrixView } from "../components/ResearchPanels";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, Select, Tabs } from "../components/ui";
import { MarkdownView } from "../components/Markdown";

const DIMENSIONS = ["研究方法", "实验设计", "创新点", "局限性", "研究结论", "可复现性"];

interface Result {
  content: string;
  citations: Citation[];
  local: boolean;
  analysisId?: string;
  evidenceCount?: number;
}

export function Research() {
  const { toast, model } = useApp();
  const { openEvidence } = useEvidence();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState(searchParams.get("tab") || "compare");
  const [papers, setPapers] = useState<Paper[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState("研究方法、实验设计与主要结论");
  const [result, setResult] = useState<Result | null>(null);
  const [matrix, setMatrix] = useState<MatrixResult | null>(null);
  const [conflicts, setConflicts] = useState<ConflictResult | null>(null);
  const [evolution, setEvolution] = useState<EvolutionResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState("pdf");
  const [exporting, setExporting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [gapCollection, setGapCollection] = useState("");
  const [fragments, setFragments] = useState<{ paper: Paper; chunk: OutlineChunk }[]>([]);
  const [fragmentPicker, setFragmentPicker] = useState<Paper | null>(null);
  const [fragmentChunks, setFragmentChunks] = useState<OutlineChunk[]>([]);
  const [fragmentQuery, setFragmentQuery] = useState("");

  const load = useCallback(async () => {
    try {
      const [paperResponse, collectionResponse] = await Promise.all([
        api<{ items: Paper[] }>("/papers?limit=200&status=ready"),
        api<{ items: Collection[] }>("/collections"),
      ]);
      setPapers(paperResponse.items);
      setCollections(collectionResponse.items);
    } catch {
      toast("无法加载论文", "error");
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (tab === "gap" && searchParams.get("collection")) {
      setGapCollection(searchParams.get("collection") || "");
    }
  }, [tab, searchParams]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return papers;
    return papers.filter(
      (paper) =>
        paper.title.toLowerCase().includes(needle) ||
        (paper.authors || "").toLowerCase().includes(needle) ||
        (paper.abstract || "").toLowerCase().includes(needle),
    );
  }, [papers, query]);

  function toggle(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  async function runCompare() {
    if (selected.length < 2) {
      toast("请至少选择两篇论文", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    setSaved(false);
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; analysis_id?: string; evidence_count?: number }>("/research/compare", {
        method: "POST",
        body: { paper_ids: selected, focus },
      });
      setResult({ ...response, analysisId: response.analysis_id, evidenceCount: response.evidence_count });
    } catch (requestError) {
      setError((requestError as Error).message || "对比失败");
    } finally {
      setRunning(false);
    }
  }

  async function runGap() {
    if (selected.length === 0 && !gapCollection) {
      toast("请选择论文或合集", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; analysis_id?: string; evidence_count?: number }>("/research/gap", {
        method: "POST",
        body: { paper_ids: selected, collection_id: gapCollection || null },
      });
      setResult({ ...response, analysisId: response.analysis_id, evidenceCount: response.evidence_count });
    } catch (requestError) {
      setError((requestError as Error).message || "分析失败");
    } finally {
      setRunning(false);
    }
  }

  async function runFragments() {
    if (fragments.length < 2) {
      toast("请至少选择两个片段", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const response = await api<{ content: string; citations: Citation[]; local: boolean; analysis_id?: string; evidence_count?: number }>("/research/compare", {
        method: "POST",
        body: {
          paper_ids: Array.from(new Set(fragments.map((item) => item.paper.id))),
          focus,
          fragments: fragments.map((item) => ({
            paper_id: item.paper.id,
            chunk_id: item.chunk.id,
            text: item.chunk.preview,
            page: item.chunk.page_start,
            section: item.chunk.section,
          })),
        },
      });
      setResult({ ...response, analysisId: response.analysis_id, evidenceCount: response.evidence_count });
    } catch (requestError) {
      setError((requestError as Error).message || "对比失败");
    } finally {
      setRunning(false);
    }
  }

  async function runMatrix() {
    if (selected.length < 1) {
      toast("请至少选择一篇论文", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setMatrix(null);
    try {
      const response = await api<MatrixResult>("/research/matrix", { method: "POST", body: { paper_ids: selected } });
      setMatrix(response);
    } catch (requestError) {
      setError((requestError as Error).message || "证据矩阵生成失败");
    } finally {
      setRunning(false);
    }
  }

  async function runConflicts() {
    if (selected.length < 2) {
      toast("冲突检测至少需要两篇论文", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setConflicts(null);
    try {
      const response = await api<ConflictResult>("/research/conflicts", { method: "POST", body: { paper_ids: selected } });
      setConflicts(response);
    } catch (requestError) {
      setError((requestError as Error).message || "冲突分析失败");
    } finally {
      setRunning(false);
    }
  }

  async function runEvolution() {
    if (selected.length < 2) {
      toast("方法演化至少需要两篇论文", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setEvolution(null);
    try {
      const response = await api<EvolutionResult>("/research/evolution", { method: "POST", body: { paper_ids: selected } });
      setEvolution(response);
    } catch (requestError) {
      setError((requestError as Error).message || "方法演化分析失败");
    } finally {
      setRunning(false);
    }
  }

  function openPaper(paperId: string, page?: number, chunkId?: string) {
    const params = new URLSearchParams();
    if (page) params.set("page", String(page));
    if (chunkId) params.set("chunk", chunkId);
    navigate("/app/papers/" + paperId + (params.toString() ? "?" + params.toString() : ""));
  }

  async function openFragmentPicker(paper: Paper) {
    setFragmentPicker(paper);
    setFragmentQuery("");
    try {
      const response = await api<{ chunks: OutlineChunk[] }>("/papers/" + paper.id + "/outline");
      setFragmentChunks(response.chunks);
    } catch {
      toast("无法读取论文章节", "error");
    }
  }

  async function saveResult() {
    if (!result?.content) return;
    try {
      await api("/knowledge", {
        method: "POST",
        body: {
          title: "多论文研究 · " + focus.slice(0, 40),
          content: result.content,
          kind: "summary",
          tags: ["multi-paper", "comparison"],
          source_paper_id: selected[0],
        },
      });
      setSaved(true);
      toast("研究结论已保存", "success");
    } catch {
      toast("保存失败", "error");
    }
  }

  async function exportResult() {
    if (!result?.content) return;
    setExporting(true);
    try {
      const response = await api<{ export: { download_url: string; filename: string } }>("/exports", {
        method: "POST",
        body: {
          kind: tab === "gap" ? "research-gap" : "comparison",
          format: exportFormat,
          title: (tab === "gap" ? "研究缺口分析 · " : "多论文对比 · ") + focus.slice(0, 40),
          content: result.content,
        },
      });
      await downloadFile(response.export.download_url, response.export.filename);
      toast("报告已导出", "success");
      setExportOpen(false);
    } catch {
      toast("导出失败", "error");
    } finally {
      setExporting(false);
    }
  }

  const selectedPapers = papers.filter((paper) => selected.includes(paper.id));

  return (
    <div className="page page-research">
      <header className="page-head">
        <div>
          <span className="eyebrow">Multi-paper research</span>
          <h1>多论文研究</h1>
          <p>把同一主题的论文放在一起，让 AI 做有证据的横向比较，而不是泛泛而谈。</p>
        </div>
        <Badge tone={model?.configured ? "accent" : "warn"}>{model?.configured ? "生成式对比" : "证据矩阵"}</Badge>
      </header>

      <Tabs
        items={[
          { id: "compare", label: "综合对比", count: selected.length || undefined },
          { id: "fragments", label: "片段对比", count: fragments.length || undefined },
          { id: "gap", label: "研究缺口" },
          { id: "matrix", label: "证据矩阵" },
          { id: "conflicts", label: "观点冲突" },
          { id: "evolution", label: "方法演化" },
        ]}
        value={tab}
        onChange={(next) => {
          setTab(next);
          setResult(null);
          setMatrix(null);
          setConflicts(null);
          setEvolution(null);
          setError(null);
        }}
      />

      <div className="research-grid">
        <section className="research-main">
          {tab !== "fragments" ? (
            <>
              <Card className="research-select">
                <div className="research-select-head">
                  <div>
                    <strong>选择论文</strong>
                    <span>已选 {selected.length} 篇 · 建议 2-5 篇</span>
                  </div>
                  <div className="research-search">
                    <Search size={14} />
                    <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选论文" />
                  </div>
                </div>
                <div className="research-paper-list">
                  {filtered.length === 0 && <p className="muted">还没有已解析的论文。</p>}
                  {filtered.map((paper) => (
                    <button
                      key={paper.id}
                      className={cn("research-paper", selected.includes(paper.id) && "active")}
                      onClick={() => toggle(paper.id)}
                    >
                      <span className="picker-check">{selected.includes(paper.id) && <Check size={12} />}</span>
                      <span className="research-paper-meta">
                        <strong>{truncate(paper.title, 70)}</strong>
                        <small>{paper.authors ? truncate(paper.authors, 46) + " · " : ""}{paper.year || "n.d."} · {paper.page_count} 页</small>
                      </span>
                    </button>
                  ))}
                </div>
                <div className="research-select-foot">
                  <Button size="sm" variant="ghost" onClick={() => setSelected(filtered.map((paper) => paper.id))}>
                    全选当前列表
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
                    清空
                  </Button>
                </div>
              </Card>

              {tab === "gap" && (
                <Card className="research-focus">
                  <Field label="或选择一个合集作为研究范围">
                    <Select value={gapCollection} onChange={(event) => setGapCollection(event.target.value)}>
                      <option value="">不使用合集</option>
                      {collections.map((collection) => (
                        <option key={collection.id} value={collection.id}>
                          {collection.name}（{collection.paper_count} 篇）
                        </option>
                      ))}
                    </Select>
                  </Field>
                </Card>
              )}

              {tab === "matrix" || tab === "conflicts" || tab === "evolution" ? (
                <Card className="research-focus p4-run">
                  <div className="p4-run-copy">
                    <strong>
                      {tab === "matrix" ? "构建研究证据矩阵" : tab === "conflicts" ? "检测学术观点冲突" : "梳理方法演化"}
                    </strong>
                    <p>
                      {tab === "matrix"
                        ? "从每篇论文中提取研究问题、方法、数据集、指标、发现与局限；每个单元格保留页码与原文。"
                        : tab === "conflicts"
                          ? "并列不同论文的观点与实验条件；条件不可比时不会强行判定冲突。"
                          : "按真实发表年份排列方法；只有原文明确或模型给出证据时才标注继承关系。"}
                    </p>
                  </div>
                  <div className="research-run">
                    <span className="muted small">{selected.length} 篇论文 · 资料库范围</span>
                    <Button
                      variant="primary"
                      loading={running}
                      onClick={() => (tab === "matrix" ? void runMatrix() : tab === "conflicts" ? void runConflicts() : void runEvolution())}
                    >
                      {tab === "matrix" ? "生成矩阵" : tab === "conflicts" ? "检测冲突" : "生成时间线"}
                    </Button>
                  </div>
                </Card>
              ) : (
              <Card className="research-focus">
                <Field label={tab === "gap" ? "关注的研究方向（可选）" : "对比维度"}>
                  <Input value={focus} onChange={(event) => setFocus(event.target.value)} placeholder="例如：训练效率、数据规模与评估方法" />
                </Field>
                <div className="dimension-chips">
                  {DIMENSIONS.map((dimension) => (
                    <button
                      key={dimension}
                      className="dimension-chip"
                      onClick={() => setFocus((current) => (current.includes(dimension) ? current : (current ? current + "、" : "") + dimension))}
                    >
                      + {dimension}
                    </button>
                  ))}
                </div>
                <div className="research-run">
                  <span className="muted small">
                    {selected.length} 篇论文 · {tab === "gap" ? "将检索局限、分歧与未来工作表述" : "将按章节定位原文证据"}
                  </span>
                  <Button variant="primary" loading={running} onClick={() => (tab === "gap" ? void runGap() : void runCompare())}>
                    {tab === "gap" ? "分析研究缺口" : "开始对比"}
                  </Button>
                </div>
              </Card>
              )}
            </>
          ) : (
            <>
              <Card className="research-select">
                <div className="research-select-head">
                  <div>
                    <strong>自选片段</strong>
                    <span>从不同论文中挑出具体片段进行比较</span>
                  </div>
                </div>
                <div className="fragment-papers">
                  {papers.map((paper) => (
                    <button key={paper.id} className="fragment-paper" onClick={() => void openFragmentPicker(paper)}>
                      <FileText size={14} />
                      <span>{truncate(paper.title, 40)}</span>
                      <Plus size={13} />
                    </button>
                  ))}
                  {papers.length === 0 && <p className="muted">先上传并解析论文。</p>}
                </div>
              </Card>

              <Card className="research-focus">
                <div className="fragment-list">
                  {fragments.length === 0 && <p className="muted">还没有选择片段。点击上方论文，挑选方法或实验片段。</p>}
                  {fragments.map((item, index) => (
                    <div key={item.chunk.id} className="fragment-item">
                      <div className="fragment-item-head">
                        <span className="fragment-key">F{index + 1}</span>
                        <strong>{truncate(item.paper.title, 50)}</strong>
                        <span>p.{item.chunk.page_start} · {item.chunk.section}</span>
                        <IconButton label="移除片段" onClick={() => setFragments((current) => current.filter((fragment) => fragment.chunk.id !== item.chunk.id))}>
                          <X size={13} />
                        </IconButton>
                      </div>
                      <p>{item.chunk.preview}</p>
                    </div>
                  ))}
                </div>
                <Field label="比较关注点">
                  <Input value={focus} onChange={(event) => setFocus(event.target.value)} />
                </Field>
                <div className="research-run">
                  <span className="muted small">{fragments.length} 个片段</span>
                  <Button variant="primary" loading={running} onClick={() => void runFragments()}>
                    比较这些片段
                  </Button>
                </div>
              </Card>
            </>
          )}

          {error && <div className="research-error">{error}</div>}

          {running && (
            <Card className="research-loading">
              <Loader2 size={20} className="spin" />
              <div>
                <strong>正在检索并组织证据…</strong>
                <span>定位章节、比对方法、检查实验条件。生成式模型通常需要 10-40 秒。</span>
              </div>
            </Card>
          )}

          {result && (
            <Card className="research-result">
              <div className="research-result-head">
                <div>
                  <h2>{tab === "gap" ? "研究缺口线索" : tab === "fragments" ? "片段对比" : "多论文对比"}</h2>
                  <span>{result.local ? "本地证据模式 · 未经过生成式改写" : "生成式分析 · 每个判断附来源"}</span>
                </div>
                <div className="research-result-actions">
                  {result.analysisId && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<ShieldCheck size={13} />}
                      onClick={() => openEvidence("analysis", result.analysisId!, "多论文研究")}
                    >
                      证据 {result.evidenceCount ? result.evidenceCount : ""}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" icon={saved ? <Check size={13} /> : <BookmarkPlus size={13} />} onClick={() => void saveResult()} disabled={saved}>
                    {saved ? "已保存" : "保存到知识库"}
                  </Button>
                  <Button size="sm" variant="secondary" icon={<Download size={13} />} onClick={() => setExportOpen(true)}>
                    导出报告
                  </Button>
                </div>
              </div>
              <MarkdownView content={result.content} />
              {result.citations.length > 0 && (
                <div className="result-sources">
                  <h3><Quote size={14} /> 原文来源（{result.citations.length}）</h3>
                  <div className="result-source-grid">
                    {result.citations.slice(0, 8).map((citation) => (
                      <button
                        key={citation.key + citation.chunk_id}
                        className="result-source"
                        onClick={() => navigate("/app/papers/" + citation.paper_id + "?page=" + citation.page)}
                      >
                        <span className="source-key">{citation.key}</span>
                        <strong>{truncate(citation.paper_title, 46)}</strong>
                        <small>p.{citation.page} · {truncate(citation.section, 26)}</small>
                        <p>{truncate(citation.quote, 110)}</p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}

          {tab === "gap" && result && (
            <GapValidationPanel paperIds={selected} onOpen={openPaper} />
          )}

          {tab === "matrix" && matrix && <MatrixView data={matrix} onOpen={openPaper} />}
          {tab === "conflicts" && conflicts && <ConflictView data={conflicts} onOpen={openPaper} />}
          {tab === "evolution" && evolution && <EvolutionView data={evolution} onOpen={openPaper} />}
        </section>

        <aside className="research-rail">
          <Card className="rail-card">
            <div className="rail-card-head"><span>对比方法</span><Scale size={15} /></div>
            <ol className="research-steps">
              <li><span>1</span>选择 2-5 篇主题相关的论文</li>
              <li><span>2</span>指定对比维度或使用默认维度</li>
              <li><span>3</span>AI 定位每篇论文的对应章节</li>
              <li><span>4</span>核对引用，保存为研究结论</li>
            </ol>
          </Card>
          <Card className="rail-card">
            <div className="rail-card-head"><span>当前选择</span><Layers size={15} /></div>
            {selectedPapers.length === 0 ? (
              <p className="rail-empty">尚未选择论文</p>
            ) : (
              <ul className="rail-papers">
                {selectedPapers.slice(0, 5).map((paper) => (
                  <li key={paper.id}>
                    <button onClick={() => navigate("/app/papers/" + paper.id)}>
                      <span className="rail-paper-icon"><FileText size={13} /></span>
                      <span className="rail-paper-meta">
                        <strong>{truncate(paper.title, 44)}</strong>
                        <small>{paper.year || "n.d."} · {paper.page_count} 页</small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="rail-card callout-card">
            <Target size={17} />
            <strong>研究缺口 ≠ 领域空白</strong>
            <p>PaperLens 只基于你的资料库给出候选线索，并说明验证方式。不要把有限文献的结论当成整个领域的定论。</p>
          </Card>
        </aside>
      </div>

      <Modal
        open={Boolean(fragmentPicker)}
        onClose={() => setFragmentPicker(null)}
        title="选择片段"
        subtitle={fragmentPicker ? "《" + truncate(fragmentPicker.title, 40) + "》" : undefined}
        size="lg"
      >
        <div className="picker-search">
          <Search size={15} />
          <Input value={fragmentQuery} onChange={(event) => setFragmentQuery(event.target.value)} placeholder="按章节或片段内容筛选" />
        </div>
        <div className="chunk-picker-list">
          {fragmentChunks
            .filter((chunk) => !fragmentQuery || (chunk.section + chunk.preview).toLowerCase().includes(fragmentQuery.toLowerCase()))
            .map((chunk) => (
              <button
                key={chunk.id}
                className="chunk-picker-item"
                onClick={() => {
                  if (!fragmentPicker) return;
                  setFragments((current) =>
                    current.some((item) => item.chunk.id === chunk.id)
                      ? current
                      : [...current, { paper: fragmentPicker, chunk }],
                  );
                  setFragmentPicker(null);
                  toast("片段已加入比较", "success");
                }}
              >
                <span className="chunk-page">p.{chunk.page_start}</span>
                <span className="chunk-meta">
                  <strong>{chunk.section}</strong>
                  <small>{chunk.preview}</small>
                </span>
                <Plus size={14} />
              </button>
            ))}
        </div>
      </Modal>

      <Modal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title="导出对比报告"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setExportOpen(false)}>取消</Button>
            <Button variant="primary" loading={exporting} onClick={() => void exportResult()}>生成并下载</Button>
          </>
        }
      >
        <Field label="文件格式">
          <Select value={exportFormat} onChange={(event) => setExportFormat(event.target.value)}>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
            <option value="md">Markdown</option>
            <option value="json">JSON</option>
          </Select>
        </Field>
        <p className="muted small">导出内容包含对比结论与引用页码，可直接用于组会或开题材料。</p>
      </Modal>
    </div>
  );
}