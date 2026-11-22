import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Download,
  FileText,
  FolderKanban,
  Plus,
  Target,
  Trash2,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, downloadFile } from "../lib/api";
import type { Paper, Project, ProjectItem } from "../lib/types";
import { cn, formatDate, relativeTime, truncate } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Field, IconButton, Input, Modal, ProgressBar, Select, Textarea } from "../components/ui";
import { PaperPicker } from "../components/PaperPicker";

export function Projects() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState<string | null>(searchParams.get("project"));
  const [detail, setDetail] = useState<{ project: Project; items: ProjectItem[] } | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<{ name: string; goal: string; description: string; paper_ids: string[] }>({ name: "", goal: "", description: "", paper_ids: [] });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [toDelete, setToDelete] = useState<Project | null>(null);
  const [exporting, setExporting] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const [projectResponse, paperResponse] = await Promise.all([
        api<{ items: Project[] }>("/projects"),
        api<{ items: Paper[] }>("/papers?limit=100"),
      ]);
      setProjects(projectResponse.items);
      setPapers(paperResponse.items);
    } catch {
      toast("无法加载项目", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      const response = await api<{ project: Project; items: ProjectItem[] }>("/projects/" + id);
      setDetail(response);
    } catch {
      toast("无法加载项目详情", "error");
    }
  }, [toast]);

  useEffect(() => {
    if (activeId) void loadDetail(activeId);
    else setDetail(null);
  }, [activeId, loadDetail]);

  async function createProject() {
    if (!form.name.trim()) {
      toast("请填写项目名称", "error");
      return;
    }
    try {
      const response = await api<{ project: Project }>("/projects", { method: "POST", body: form });
      toast("项目已创建，进入研究对话", "success");
      setCreateOpen(false);
      setForm({ name: "", goal: "", description: "", paper_ids: [] });
      navigate("/app?project=" + response.project.id);
    } catch {
      toast("创建失败", "error");
    }
  }

  async function updateProject(patch: Partial<Project>) {
    if (!detail) return;
    try {
      const response = await api<{ project: Project }>("/projects/" + detail.project.id, { method: "PATCH", body: patch });
      setDetail({ ...detail, project: response.project });
      setProjects((current) => current.map((project) => (project.id === response.project.id ? response.project : project)));
    } catch {
      toast("更新失败", "error");
    }
  }

  async function addPapers(ids: string[], selectedPapers: Paper[]) {
    if (!detail) return;
    try {
      for (const paper of selectedPapers) {
        const response = await api<{ item: ProjectItem }>("/projects/" + detail.project.id + "/items", {
          method: "POST",
          body: { kind: "paper", ref_id: paper.id, title: paper.title },
        });
      }
      setDetail({ ...detail, items: [...detail.items] });
      toast("论文已加入项目", "success");
    } catch {
      toast("添加失败", "error");
    }
  }

  async function removeItem(item: ProjectItem) {
    if (!detail) return;
    try {
      await api("/projects/" + detail.project.id + "/items/" + item.id, { method: "DELETE" });
      setDetail({ ...detail, items: detail.items.filter((row) => row.id !== item.id) });
    } catch {
      toast("移除失败", "error");
    }
  }

  async function removeProject() {
    if (!toDelete) return;
    try {
      await api("/projects/" + toDelete.id, { method: "DELETE" });
      setProjects((current) => current.filter((project) => project.id !== toDelete.id));
      if (activeId === toDelete.id) {
        setActiveId(null);
        setSearchParams({});
      }
      setToDelete(null);
      toast("项目已删除", "success");
    } catch {
      toast("删除失败", "error");
    }
  }

  async function exportProject() {
    if (!detail) return;
    setExporting(true);
    try {
      const response = await api<{ export: { download_url: string; filename: string } }>("/exports", {
        method: "POST",
        body: { kind: "project", format: "md", title: detail.project.name, project_id: detail.project.id },
      });
      await downloadFile(response.export.download_url, response.export.filename);
      toast("项目已导出", "success");
    } catch {
      toast("导出失败", "error");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="page page-projects">
      <header className="page-head">
        <div>
          <span className="eyebrow">Research projects</span>
          <h1>研究项目</h1>
          <p>把论文、知识与研究问题组织成一条独立的研究线，数据在项目之间保持隔离。</p>
        </div>
        <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
          新建项目
        </Button>
      </header>

      {loading ? (
        <div className="projects-grid">{[0, 1, 2].map((index) => <div key={index} className="skeleton skeleton-card" />)}</div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<FolderKanban size={26} />}
          title="还没有研究项目"
          description="一个项目可以包含研究目标、相关论文、笔记、知识片段与 AI 分析结果。"
          action={<Button variant="primary" onClick={() => setCreateOpen(true)}>建立第一个项目</Button>}
        />
      ) : (
        <div className="projects-layout">
          <div className="projects-list">
            {projects.map((project) => (
              <button
                key={project.id}
                className={cn("project-card", activeId === project.id && "active")}
                onClick={() => {
                  setActiveId(project.id);
                  setSearchParams({ project: project.id });
                }}
              >
                <div className="project-card-head">
                  <span className="project-dot" style={{ background: project.color }} />
                  <strong>{project.name}</strong>
                  <span>{project.progress}%</span>
                </div>
                <p>{project.goal || project.description || "尚未填写研究目标"}</p>
                <ProgressBar value={project.progress} />
                <div className="project-card-foot">
                  <span>{project.counts.paper || 0} 论文</span>
                  <span>{relativeTime(project.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="projects-detail">
            {!detail ? (
              <Card className="project-placeholder">
                <Target size={24} />
                <h3>选择一个项目查看详情</h3>
                <p>或者创建新的研究项目，把当前的阅读与结论集中管理。</p>
              </Card>
            ) : (
              <>
                <Card className="project-head-card">
                  <div className="project-title-row">
                    <div>
                      <span className="eyebrow">Project</span>
                      <h2>{detail.project.name}</h2>
                    </div>
                    <div className="project-actions">
                      <IconButton label="导出项目" onClick={() => void exportProject()}><Download size={16} /></IconButton>
                      <IconButton label="删除项目" onClick={() => setToDelete(detail.project)}><Trash2 size={16} /></IconButton>
                    </div>
                  </div>
                  <Field label="研究目标">
                    <Textarea
                      rows={2}
                      defaultValue={detail.project.goal || ""}
                      onBlur={(event) => event.target.value !== detail.project.goal && void updateProject({ goal: event.target.value })}
                      placeholder="这个项目想回答什么问题？"
                    />
                  </Field>
                  <div className="project-progress-row">
                    <span>进度</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={detail.project.progress}
                      onChange={(event) => setDetail({ ...detail, project: { ...detail.project, progress: Number(event.target.value) } })}
                      onMouseUp={() => void updateProject({ progress: detail.project.progress })}
                      onTouchEnd={() => void updateProject({ progress: detail.project.progress })}
                    />
                    <strong>{detail.project.progress}%</strong>
                  </div>
                  <div className="project-meta">
                    <span>创建于 {formatDate(detail.project.created_at)}</span>
                    <Badge tone="accent">{detail.project.status === "active" ? "进行中" : detail.project.status}</Badge>
                  </div>
                </Card>

                <Card className="project-items-card">
                  <div className="project-items-head">
                    <h3>项目论文（{detail.items.filter((item) => item.kind === "paper").length}）</h3>
                    <Button size="sm" variant="ghost" icon={<FileText size={13} />} onClick={() => setPickerOpen(true)}>
                      添加论文
                    </Button>
                  </div>
                  {detail.items.filter((item) => item.kind === "paper").length === 0 ? (
                    <p className="muted">还没有论文。添加论文后即可在 Chat 中围绕项目提问。</p>
                  ) : (
                    <ul className="project-item-list">
                      {detail.items.filter((item) => item.kind === "paper").map((item) => (
                        <li key={item.id}>
                          <span className="item-kind paper"><FileText size={13} /></span>
                          <div>
                            <strong>{item.title}</strong>
                          </div>
                          <div className="item-actions">
                            {item.ref_id && (
                              <button onClick={() => navigate("/app/papers/" + item.ref_id)}>打开 <ArrowRight size={12} /></button>
                            )}
                            <IconButton label="移除" onClick={() => void removeItem(item)}><Trash2 size={13} /></IconButton>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </>
            )}
          </div>
        </div>
      )}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="新建研究项目"
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" onClick={() => void createProject()}>创建</Button>
          </>
        }
      >
        <Field label="项目名称">
          <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：基于大语言模型的文献检索" />
        </Field>
        <Field label="研究目标">
          <Textarea rows={3} value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })} placeholder="这个项目想解决什么问题？" />
        </Field>
        <Field label="描述">
          <Input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
        </Field>
        <Field label="研究论文">
          <div className="project-create-papers">
            {papers.filter((paper) => paper.status === "ready").length === 0 ? (
              <p className="muted small">资料库还没有已解析论文；也可以先创建空项目。</p>
            ) : papers.filter((paper) => paper.status === "ready").map((paper) => (
              <label key={paper.id} className="project-create-paper">
                <input
                  type="checkbox"
                  checked={form.paper_ids.includes(paper.id)}
                  onChange={(event) => setForm({
                    ...form,
                    paper_ids: event.target.checked
                      ? [...form.paper_ids, paper.id]
                      : form.paper_ids.filter((id) => id !== paper.id),
                  })}
                />
                <span>{paper.title}</span>
              </label>
            ))}
          </div>
          <p className="muted small">创建后直接进入 Chat，项目论文会自动成为研究范围。</p>
        </Field>
      </Modal>

      <PaperPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="添加论文到项目"
        onConfirm={(ids, selectedPapers) => void addPapers(ids, selectedPapers)}
      />

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这个项目？"
        description={toDelete ? "《" + toDelete.name + "》中的笔记与论文关联会被移除，但论文本身仍保留在资料库。" : undefined}
        confirmLabel="删除项目"
        danger
        onConfirm={() => void removeProject()}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}