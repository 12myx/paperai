import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CircleStop,
  ExternalLink,
  ListChecks,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { useEvidence } from "../store/EvidenceContext";
import { api, streamTask } from "../lib/api";
import type { AgentTask, TaskDetail } from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Badge, Button, Card, EmptyState, Select, Spinner } from "../components/ui";
import { SelfCheckCard } from "../components/Chat";
import { MarkdownView } from "../components/Markdown";

const STATUS_LABEL: Record<string, string> = {
  queued: "待执行",
  running: "运行中",
  paused: "已暂停",
  cancelled: "已取消",
  completed: "已完成",
  failed: "失败",
};

const STATUS_TONE: Record<string, "neutral" | "accent" | "warn" | "danger"> = {
  queued: "neutral",
  running: "accent",
  paused: "warn",
  cancelled: "neutral",
  completed: "accent",
  failed: "danger",
};

export function Tasks() {
  const { toast } = useApp();
  const { openEvidence } = useEvidence();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api<{ items: AgentTask[] }>("/agent/tasks?limit=60");
      setTasks(response.items);
      if (!selectedId && response.items.length > 0) setSelectedId(response.items[0].id);
    } catch (error) {
      toast((error as Error).message || "无法加载任务", "error");
    } finally {
      setLoading(false);
    }
  }, [selectedId, toast]);

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    try {
      const response = await api<TaskDetail>("/agent/tasks/" + id);
      setDetail(response);
    } catch (error) {
      toast((error as Error).message || "无法加载任务详情", "error");
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!detail) return;
    if (!["running", "paused"].includes(detail.task.status)) return;
    const timer = window.setInterval(() => {
      void loadDetail(detail.task.id);
      void loadTasks();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [detail, loadDetail, loadTasks]);

  const filtered = useMemo(
    () => (filter === "all" ? tasks : tasks.filter((task) => task.status === filter)),
    [filter, tasks],
  );

  async function execute(taskId: string) {
    setBusy(true);
    try {
      await streamTask(taskId, {
        onEvent: () => undefined,
        onError: (error) => toast(error.message || "执行失败", "error"),
      });
      await loadDetail(taskId);
      await loadTasks();
    } finally {
      setBusy(false);
    }
  }

  async function action(kind: "pause" | "resume" | "cancel") {
    if (!detail) return;
    setBusy(true);
    try {
      await api("/agent/tasks/" + detail.task.id + "/" + kind, { method: "POST" });
      await loadDetail(detail.task.id);
      await loadTasks();
    } catch (error) {
      toast((error as Error).message || "操作失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function rerun() {
    if (!detail) return;
    setBusy(true);
    try {
      const response = await api<{ task: AgentTask }>("/agent/tasks/" + detail.task.id + "/rerun", { method: "POST" });
      setSelectedId(response.task.id);
      await loadTasks();
      await execute(response.task.id);
    } catch (error) {
      toast((error as Error).message || "重跑失败", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page page-tasks">
      <header className="page-head">
        <div>
          <span className="eyebrow"><ListChecks size={12} /> Agent task center</span>
          <h1>任务中心</h1>
          <p>查看计划、执行状态、自检报告；支持暂停、继续、取消与重跑。取消的任务不会写入新消息。</p>
        </div>
        <Button variant="secondary" icon={<RefreshCw size={14} />} onClick={() => { void loadTasks(); if (selectedId) void loadDetail(selectedId); }}>
          刷新
        </Button>
      </header>

      <div className="task-layout">
        <Card className="task-list-card">
          <div className="p4-filters" style={{ padding: "6px 6px 2px" }}>
            <Select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="按任务状态筛选">
              <option value="all">全部任务</option>
              {Object.entries(STATUS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </Select>
          </div>
          {loading ? (
            <div className="task-empty"><Spinner size={15} /> 加载任务…</div>
          ) : filtered.length === 0 ? (
            <div className="task-empty">还没有任务。发起一个复杂问题，会先生成计划。</div>
          ) : (
            <div className="task-list">
              {filtered.map((task) => (
                <button
                  key={task.id}
                  className={cn("task-list-item", selectedId === task.id && "active")}
                  onClick={() => setSelectedId(task.id)}
                >
                  <div className="task-list-head">
                    <Badge tone={STATUS_TONE[task.status]}>{STATUS_LABEL[task.status] || task.status}</Badge>
                    <span className="task-list-meta">{task.mode}</span>
                  </div>
                  <strong>{truncate(task.goal, 72)}</strong>
                  <span className="task-list-meta">
                    {task.progress}% · {task.plan.length} 步 · {formatDate(task.created_at)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className="task-detail">
          {detailLoading && !detail ? (
            <div className="task-empty"><Spinner size={15} /> 加载详情…</div>
          ) : !detail ? (
            <EmptyState icon={<ListChecks size={26} />} title="选择一个任务" description="左侧列表显示计划、执行状态与自检结果。" />
          ) : (
            <>
              <div className="task-detail-head">
                <div>
                  <div className="task-list-head">
                    <Badge tone={STATUS_TONE[detail.task.status]}>{STATUS_LABEL[detail.task.status] || detail.task.status}</Badge>
                    <span className="task-list-meta">{detail.task.mode} · {detail.task.plan.length} 步</span>
                  </div>
                  <h2>{detail.task.goal}</h2>
                  <div className="task-detail-meta">
                    <span>范围 {detail.task.scope_type}</span>
                    <span>进度 {detail.task.progress}%</span>
                    {detail.task.current_step && <span>当前：{detail.task.current_step}</span>}
                    <span>{formatDate(detail.task.created_at)}</span>
                  </div>
                </div>
                <div className="task-actions">
                  {detail.task.status === "queued" && (
                    <Button size="sm" variant="primary" icon={<Play size={13} />} loading={busy} onClick={() => void execute(detail.task.id)}>执行</Button>
                  )}
                  {detail.task.status === "running" && (
                    <Button size="sm" variant="secondary" icon={<Pause size={13} />} loading={busy} onClick={() => void action("pause")}>暂停</Button>
                  )}
                  {detail.task.status === "paused" && (
                    <Button size="sm" variant="primary" icon={<Play size={13} />} loading={busy} onClick={() => void action("resume")}>继续</Button>
                  )}
                  {["running", "paused"].includes(detail.task.status) && (
                    <Button size="sm" variant="ghost" icon={<CircleStop size={13} />} loading={busy} onClick={() => void action("cancel")}>取消</Button>
                  )}
                  {["completed", "failed", "cancelled"].includes(detail.task.status) && (
                    <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={busy} onClick={() => void rerun()}>重跑</Button>
                  )}
                  {detail.task.conversation_id && (
                    <Button size="sm" variant="ghost" icon={<ArrowRight size={13} />} onClick={() => navigate("/app?conversation=" + detail.task.conversation_id)}>对话</Button>
                  )}
                </div>
              </div>
              <div className="task-progress"><span style={{ width: Math.max(2, detail.task.progress) + "%" }} /></div>

              <div className="task-section">
                <h3><ListChecks size={13} /> 计划</h3>
                <div className="task-plan-list">
                  {detail.task.plan.map((step, index) => (
                    <div key={step.id || index} className="task-plan-row">
                      <span className="plan-step-index">{String(index + 1).padStart(2, "0")}</span>
                      <span>{step.title}</span>
                      <span>{step.tool || "推理"} · {step.status}</span>
                    </div>
                  ))}
                </div>
              </div>

              {detail.task.self_check && Object.keys(detail.task.self_check).length > 0 && (
                <div className="task-section task-self">
                  <SelfCheckCard check={detail.task.self_check as never} />
                </div>
              )}

              {detail.result_message?.content && (
                <div className="task-section">
                  <h3><ShieldCheck size={13} /> 结果</h3>
                  <MarkdownView content={detail.result_message.content} />
                  {detail.result_message.id && (
                    <Button size="sm" variant="ghost" icon={<ExternalLink size={12} />} onClick={() => openEvidence("message", detail.result_message!.id)}>
                      查看证据
                    </Button>
                  )}
                </div>
              )}

              {detail.task.error && <div className="msg-error">{detail.task.error}</div>}
            </>
          )}
        </Card>
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
