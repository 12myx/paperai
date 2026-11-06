import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowUp,
  BookmarkPlus,
  Check,
  ChevronDown,
  ChevronRight,
  CircleStop,
  Copy,
  ExternalLink,
  FileText,
  Loader2,
  Paperclip,
  Pause,
  Play,
  Quote,
  RefreshCw,
  ShieldCheck,
  Save,
  Sparkles,
  ListChecks,
  Wrench,
  X,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { useEvidence } from "../store/EvidenceContext";
import { api, copyText, streamChat, streamTask, uploadPdf } from "../lib/api";
import type { AgentPlanStep, AgentSelfCheck, AgentStep, AgentTask, ChatMessage, Citation, PendingAction, ScopeSelection, StreamEvent } from "../lib/types";
import { cn, MODES, truncate } from "../lib/utils";
import { Badge, Button, IconButton, Spinner } from "./ui";
import { MarkdownView } from "./Markdown";
import { Uploader } from "./Uploader";

/* ------------------------------------------------------------------ hook */

const PLAN_RE = /(研究计划|实验设计|文献综述|综述|开题|研究缺口|对比|比较|矩阵|冲突|演化|研究情报|趋势|研究机会|报告|多篇|这些论文|全部论文|survey|literature review|research plan|experiment design|compare|gap|matrix|conflict|evolution|opportunit)/i;

function shouldPlan(message: string, mode: string): boolean {
  return ["deep_read", "critical", "multi_paper"].includes(mode) || PLAN_RE.test(message);
}

export function useChat({
  mode,
  scope,
  onConversation,
}: {
  mode: string;
  scope: ScopeSelection;
  onConversation?: (id: string) => void;
}) {
  const { toast } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [paused, setPaused] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const pendingRef = useRef<string>("");
  const taskRef = useRef<string>("");
  const modeRef = useRef(mode);
  const scopeRef = useRef(scope);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);
  useEffect(() => {
    scopeRef.current = scope;
  }, [scope]);

  const loadConversation = useCallback(async (id: string) => {
    try {
      const response = await api<{ conversation: { id: string }; messages: ChatMessage[] }>("/conversations/" + id);
      setConversationId(response.conversation.id);
      setMessages(
        response.messages.map((message) => ({
          ...message,
          serverId: message.id,
          citations: message.citations || [],
          steps: (message as unknown as { steps?: AgentStep[] }).steps || [],
        })),
      );
    } catch {
      toast("无法加载这段研究记录", "error");
    }
  }, [toast]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    taskRef.current = "";
    setPaused(false);
    setMessages([]);
    setConversationId(null);
    setStreaming(false);
  }, []);

  const updateMessage = useCallback((id: string, updater: (message: ChatMessage) => ChatMessage) => {
    setMessages((current) => current.map((message) => (message.id === id ? updater(message) : message)));
  }, []);

  const handleEvent = useCallback((event: StreamEvent, pendingId: string) => {
    switch (event.type) {
      case "start": {
        setConversationId(String(event.conversation_id));
        onConversation?.(String(event.conversation_id));
        if (event.task_id) taskRef.current = String(event.task_id);
        updateMessage(pendingId, (message) => ({
          ...message,
          taskId: event.task_id ? String(event.task_id) : message.taskId,
          local: event.provider === "local" ? true : message.local,
        }));
        break;
      }
      case "plan":
        if (event.plan) {
          updateMessage(pendingId, (message) => ({
            ...message,
            taskId: event.task_id ? String(event.task_id) : message.taskId,
            plan: (message.plan || event.plan) as AgentPlanStep[],
          }));
        }
        break;
      case "step": {
        const step = event.step as AgentStep;
        updateMessage(pendingId, (message) => {
          const steps = [...(message.steps || [])];
          const index = steps.findIndex((item) => item.index === step.index);
          if (index >= 0) steps[index] = { ...steps[index], ...step };
          else steps.push(step);
          return { ...message, steps };
        });
        break;
      }
      case "delta":
        updateMessage(pendingId, (message) => ({ ...message, content: message.content + String(event.text || "") }));
        break;
      case "action": {
        const action = event.action as PendingAction;
        updateMessage(pendingId, (message) => ({ ...message, actions: [...(message.actions || []), action] }));
        break;
      }
      case "notice":
        toast(String(event.message || ""), "info");
        break;
      case "paused":
        setPaused(true);
        updateMessage(pendingId, (message) => ({ ...message, planState: "paused" }));
        toast(String(event.message || "任务已暂停"), "info");
        break;
      case "resumed":
        setPaused(false);
        updateMessage(pendingId, (message) => ({ ...message, planState: "executing" }));
        toast(String(event.message || "任务已继续"), "success");
        break;
      case "cancelled":
        setPaused(false);
        setStreaming(false);
        updateMessage(pendingId, (message) => ({
          ...message,
          streaming: false,
          planState: "cancelled",
          content: message.content || "任务已取消，未写入新消息。",
        }));
        abortRef.current = null;
        break;
      case "self_check":
        updateMessage(pendingId, (message) => ({ ...message, selfCheck: event.self_check as AgentSelfCheck }));
        break;
      case "error":
        updateMessage(pendingId, (message) => ({ ...message, streaming: false, error: String(event.message) }));
        toast(String(event.message || "生成失败"), "error");
        break;
      case "done":
        setPaused(false);
        updateMessage(pendingId, (message) => ({
          ...message,
          serverId: String(event.message_id || message.serverId || ""),
          taskId: event.task_id ? String(event.task_id) : message.taskId,
          content: String(event.content || message.content),
          citations: (event.citations as Citation[]) || [],
          actions: (event.actions as PendingAction[]) || message.actions || [],
          selfCheck: (event.self_check as AgentSelfCheck) || message.selfCheck,
          streaming: false,
          planState: "completed",
        }));
        break;
      default:
        break;
    }
  }, [onConversation, toast, updateMessage]);

  const send = useCallback(
    async (text: string, options: { regenerate?: boolean } = {}) => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) return;
      const userMessage: ChatMessage = {
        id: "user-" + Date.now(),
        role: "user",
        content: trimmed,
        citations: [],
      };
      const pendingId = "assistant-" + Date.now();
      pendingRef.current = pendingId;
      const pending: ChatMessage = {
        id: pendingId,
        role: "assistant",
        content: "",
        citations: [],
        steps: [],
        actions: [],
        streaming: false,
      };
      setMessages((current) => {
        const base = options.regenerate ? current.slice(0, -1) : current;
        return options.regenerate ? [...base, pending] : [...base, userMessage, pending];
      });
      setStreaming(true);

      if (shouldPlan(trimmed, modeRef.current)) {
        try {
          const currentScope = scopeRef.current;
          const plan = await api<{ task: AgentTask; plan: AgentPlanStep[]; conversation_id: string }>("/agent/tasks/plan", {
            method: "POST",
            body: {
              message: trimmed,
              conversation_id: conversationId,
              mode: modeRef.current,
              scope_type: currentScope.type,
              scope_ids: currentScope.ids,
            },
          });
          setConversationId(plan.conversation_id);
          onConversation?.(plan.conversation_id);
          taskRef.current = plan.task.id;
          updateMessage(pendingId, (message) => ({
            ...message,
            taskId: plan.task.id,
            plan: plan.plan,
            planState: "preview",
            streaming: false,
          }));
        } catch (error) {
          updateMessage(pendingId, (message) => ({
            ...message,
            streaming: false,
            error: (error as Error).message,
            content: message.content || "无法生成任务计划。",
          }));
          toast((error as Error).message || "计划生成失败", "error");
        } finally {
          setStreaming(false);
          abortRef.current = null;
        }
        return;
      }

      const controller = new AbortController();
      abortRef.current = controller;
      const currentScope = scopeRef.current;
      await streamChat(
        {
          message: trimmed,
          conversation_id: conversationId,
          mode: modeRef.current,
          scope_type: currentScope.type,
          scope_ids: currentScope.ids,
        },
        {
          signal: controller.signal,
          onError: (error) => {
            updateMessage(pendingId, (message) => ({
              ...message,
              streaming: false,
              error: error.message,
              content: message.content || "生成失败：" + error.message,
            }));
            setStreaming(false);
            abortRef.current = null;
            toast(error.message, "error");
          },
          onEvent: (event) => handleEvent(event, pendingId),
        },
      );
      setStreaming(false);
      setPaused(false);
      abortRef.current = null;
    },
    [conversationId, handleEvent, onConversation, toast, updateMessage],
  );

  const executePlan = useCallback(async (messageId: string, taskId: string) => {
    if (abortRef.current) return;
    const controller = new AbortController();
    abortRef.current = controller;
    pendingRef.current = messageId;
    taskRef.current = taskId;
    setStreaming(true);
    setPaused(false);
    updateMessage(messageId, (message) => ({ ...message, planState: "executing", streaming: true, error: null }));
    await streamTask(taskId, {
      signal: controller.signal,
      onError: (error) => {
        updateMessage(messageId, (message) => ({ ...message, streaming: false, planState: "failed", error: error.message }));
        setStreaming(false);
        abortRef.current = null;
        toast(error.message, "error");
      },
      onEvent: (event) => handleEvent(event, messageId),
    });
    setStreaming(false);
    setPaused(false);
    abortRef.current = null;
  }, [handleEvent, toast, updateMessage]);

  const updatePlan = useCallback(async (messageId: string, taskId: string, plan: AgentPlanStep[]) => {
    try {
      const response = await api<{ plan: AgentPlanStep[] }>("/agent/tasks/" + taskId + "/plan", {
        method: "PATCH",
        body: { plan },
      });
      updateMessage(messageId, (message) => ({ ...message, plan: response.plan }));
      toast("计划已更新", "success");
    } catch (error) {
      toast((error as Error).message || "更新计划失败", "error");
    }
  }, [toast, updateMessage]);

  const pause = useCallback(async (taskId: string) => {
    try {
      await api("/agent/tasks/" + taskId + "/pause", { method: "POST" });
      setPaused(true);
    } catch (error) {
      toast((error as Error).message || "暂停失败", "error");
    }
  }, [toast]);

  const resume = useCallback(async (taskId: string) => {
    try {
      await api("/agent/tasks/" + taskId + "/resume", { method: "POST" });
      setPaused(false);
    } catch (error) {
      toast((error as Error).message || "继续失败", "error");
    }
  }, [toast]);

  const cancel = useCallback(async (messageId: string, taskId: string) => {
    try {
      await api("/agent/tasks/" + taskId + "/cancel", { method: "POST" });
    } catch (error) {
      toast((error as Error).message || "取消失败", "error");
    }
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setPaused(false);
    updateMessage(messageId, (message) => ({
      ...message,
      streaming: false,
      planState: "cancelled",
      content: message.content || "任务已取消，未写入新消息。",
    }));
  }, [toast, updateMessage]);

  const stop = useCallback(() => {
    const taskId = taskRef.current;
    if (taskId) {
      void api("/agent/tasks/" + taskId + "/cancel", { method: "POST" }).catch(() => undefined);
    }
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setPaused(false);
    const pendingId = pendingRef.current;
    updateMessage(pendingId, (message) => ({
      ...message,
      streaming: false,
      planState: taskId ? "cancelled" : message.planState,
      content: message.content || (taskId ? "任务已取消，未写入新消息。" : "已停止生成。"),
    }));
  }, [updateMessage]);

  return {
    messages,
    setMessages,
    streaming,
    paused,
    send,
    stop,
    reset,
    conversationId,
    loadConversation,
    executePlan,
    updatePlan,
    pause,
    resume,
    cancel,
  };
}

/* ------------------------------------------------------------------ messages */

export function ChatMessageItem({
  message,
  onCite,
  onRegenerate,
  showRegenerate = true,
  onExecutePlan,
  onPausePlan,
  onResumePlan,
  onCancelPlan,
  onUpdatePlan,
}: {
  message: ChatMessage;
  onCite?: (key: string) => void;
  onRegenerate?: () => void;
  showRegenerate?: boolean;
  onExecutePlan?: (messageId: string, taskId: string) => void;
  onPausePlan?: (taskId: string) => void;
  onResumePlan?: (taskId: string) => void;
  onCancelPlan?: (messageId: string, taskId: string) => void;
  onUpdatePlan?: (messageId: string, taskId: string, plan: AgentPlanStep[]) => void;
}) {
  const { toast } = useApp();
  const { openEvidence } = useEvidence();
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const handleCite = (key: string) => {
    const citation = message.citations?.find((item) => item.key === key);
    if (!citation) {
      onCite?.(key);
      return;
    }
    const params = new URLSearchParams();
    params.set("page", String(citation.page));
    if (citation.chunk_id) params.set("chunk", citation.chunk_id);
    navigate("/app/papers/" + citation.paper_id + "?" + params.toString());
  };

  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <div className="msg-user-bubble">{message.content}</div>
      </div>
    );
  }

  async function saveToKnowledge() {
    try {
      await api("/knowledge", {
        method: "POST",
        body: {
          title: truncate(message.content.replace(/[#>*\-]/g, "").replace(/\s+/g, " ").trim(), 60) || "AI 研究结论",
          content: message.content,
          kind: "summary",
          tags: ["ai-answer"],
          source_paper_id: message.citations?.[0]?.paper_id,
          source_page: message.citations?.[0]?.page,
        },
      });
      setSaved(true);
      toast("已保存到知识库", "success");
    } catch {
      toast("保存失败，请重试", "error");
    }
  }

  return (
    <div className="msg msg-assistant">
      <div className="msg-avatar">
        <Sparkles size={16} />
      </div>
      <div className="msg-main">
        <div className="msg-meta">
          <strong>PaperLens</strong>
          {message.local ? <Badge tone="warn">本地抽取</Badge> : <Badge tone="accent">AI 分析</Badge>}
          {message.model && <span className="msg-model">{message.model}</span>}
        </div>

        {message.plan && message.planState && (
          <PlanCard
            message={message}
            onExecute={onExecutePlan}
            onPause={onPausePlan}
            onResume={onResumePlan}
            onCancel={onCancelPlan}
            onUpdate={onUpdatePlan}
          />
        )}

        {message.steps && message.steps.length > 0 && <AgentTimeline steps={message.steps} />}

        {message.content ? (
          <MarkdownView content={message.content} onCite={handleCite} />
        ) : message.error || message.planState === "preview" ? null : (
          <div className="typing">
            <span />
            <span />
            <span />
            <em>正在检索论文证据…</em>
          </div>
        )}

        {message.selfCheck && <SelfCheckCard check={message.selfCheck} />}

        {message.error && <div className="msg-error">{message.error}</div>}

        {message.actions && message.actions.length > 0 && (
          <div className="action-stack">
            {message.actions.map((action, index) => (
              <ActionCard key={index} action={action} onDone={() => setSaved(true)} />
            ))}
          </div>
        )}

        {message.citations && message.citations.length > 0 && (
          <div className="sources">
            <div className="sources-head">
            <button className="sources-toggle" onClick={() => setExpanded((value) => !value)}>
              <Quote size={14} />
              {message.citations.length} 个原文来源
              <ChevronDown size={14} className={cn(expanded && "rotate-180")} />
            </button>
            {message.serverId && (
              <button className="evidence-open" onClick={() => openEvidence("message", message.serverId ?? "")}>
                <ShieldCheck size={13} /> 证据视图
              </button>
            )}
            </div>
            <div className={cn("source-list", expanded && "source-expanded")}>
              {message.citations.slice(0, expanded ? 12 : 3).map((citation) => (
                <SourceCard
                  key={citation.key + citation.chunk_id}
                  citation={citation}
                  onOpen={() => {
                    const params = new URLSearchParams();
                    params.set("page", String(citation.page));
                    if (citation.chunk_id) params.set("chunk", citation.chunk_id);
                    navigate("/app/papers/" + citation.paper_id + "?" + params.toString());
                  }}
                />
              ))}
              {!expanded && message.citations.length > 3 && (
                <button className="source-more" onClick={() => setExpanded(true)}>
                  查看全部 {message.citations.length} 个来源
                  <ChevronRight size={13} />
                </button>
              )}
            </div>
          </div>
        )}

        {!message.streaming && message.content && message.planState !== "cancelled" && (
          <div className="msg-actions">
            <button
              onClick={async () => {
                const ok = await copyText(message.content);
                toast(ok ? "已复制回答" : "复制失败", ok ? "success" : "error");
              }}
            >
              <Copy size={13} /> 复制
            </button>
            <button onClick={saveToKnowledge} disabled={saved}>
              {saved ? <Check size={13} /> : <BookmarkPlus size={13} />}
              {saved ? "已保存" : "保存到知识库"}
            </button>
            {showRegenerate && onRegenerate && (
              <button onClick={onRegenerate}>
                <RefreshCw size={13} /> 重新生成
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function PlanCard({
  message,
  onExecute,
  onPause,
  onResume,
  onCancel,
  onUpdate,
}: {
  message: ChatMessage;
  onExecute?: (messageId: string, taskId: string) => void;
  onPause?: (taskId: string) => void;
  onResume?: (taskId: string) => void;
  onCancel?: (messageId: string, taskId: string) => void;
  onUpdate?: (messageId: string, taskId: string, plan: AgentPlanStep[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const plan = message.plan || [];
  const taskId = message.taskId;
  const state = message.planState;
  const preview = state === "preview";
  const executing = state === "executing";
  const paused = state === "paused";
  const finished = state === "completed" || state === "cancelled" || state === "failed";

  function startEdit() {
    setDraft(plan.map((step) => step.title).join("\n"));
    setEditing(true);
  }

  function saveEdit() {
    const titles = draft.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!titles.length || !taskId || !onUpdate) return;
    const next = plan.map((step, index) => ({ ...step, title: titles[index] || step.title }));
    onUpdate(message.id, taskId, next);
    setEditing(false);
  }

  return (
    <div className={cn("plan-card", "plan-" + state)}>
      <div className="plan-head">
        <ListChecks size={14} />
        <strong>任务计划</strong>
        <Badge tone={preview ? "warn" : paused ? "warn" : state === "completed" ? "accent" : state === "failed" ? "danger" : "neutral"}>
          {preview ? "待确认" : paused ? "已暂停" : executing ? "执行中" : state === "completed" ? "已完成" : state === "cancelled" ? "已取消" : "已失败"}
        </Badge>
        <span className="plan-source">{message.taskId ? "任务 " + message.taskId.slice(0, 8) : ""}</span>
      </div>
      <p className="plan-note">
        {preview
          ? "先确认步骤与工具；执行后仍可暂停、继续或取消。"
          : paused
            ? "任务已停在检查点，继续后会从当前步骤恢复。"
            : state === "completed"
              ? "计划步骤已完成；下方自检给出证据覆盖与风险。"
              : state === "cancelled"
                ? "任务已取消，不会写入新消息。"
                : "只执行已列出的工具；不会把推测当作原文证据。"}
      </p>

      {editing ? (
        <div className="plan-editor">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={Math.max(4, plan.length)} />
          <div className="plan-editor-actions">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消修改</Button>
            <Button size="sm" variant="primary" onClick={saveEdit}>保存计划</Button>
          </div>
        </div>
      ) : (
        <ol className="plan-steps">
          {plan.map((step, index) => (
            <li key={step.id || index} className={cn("plan-step", "plan-step-" + step.status)}>
              <span className="plan-step-index">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{step.title}</strong>
                {step.description && <p>{step.description}</p>}
                <span className="plan-step-meta">
                  {step.tool || "推理 / 组织"} 
                  {step.depends_on?.length ? " · 依赖 " + step.depends_on.join("、") : ""}
                </span>
              </div>
              <span className="plan-step-status">
                {step.status === "completed" ? <Check size={12} /> : step.status === "failed" ? <X size={12} /> : step.status === "running" ? <Loader2 size={12} className="spin" /> : null}
              </span>
            </li>
          ))}
        </ol>
      )}

      <div className="plan-actions">
        {preview && taskId && onExecute && (
          <Button size="sm" variant="primary" icon={<Play size={13} />} onClick={() => onExecute(message.id, taskId)}>执行计划</Button>
        )}
        {preview && taskId && onUpdate && <Button size="sm" variant="ghost" onClick={startEdit}>调整步骤</Button>}
        {executing && taskId && onPause && <Button size="sm" variant="secondary" icon={<Pause size={13} />} onClick={() => onPause(taskId)}>暂停</Button>}
        {paused && taskId && onResume && <Button size="sm" variant="primary" icon={<Play size={13} />} onClick={() => onResume(taskId)}>继续</Button>}
        {(preview || executing || paused) && taskId && onCancel && (
          <Button size="sm" variant="ghost" icon={<CircleStop size={13} />} onClick={() => onCancel(message.id, taskId)}>取消任务</Button>
        )}
        {finished && !message.content && <span className="plan-ended">没有写入新回答。</span>}
      </div>
    </div>
  );
}

export function SelfCheckCard({ check }: { check: NonNullable<ChatMessage["selfCheck"]> }) {
  const [open, setOpen] = useState(true);
  const tone = check.status === "pass" ? "accent" : check.status === "fail" ? "danger" : "warn";
  return (
    <div className={cn("self-check", "self-" + check.status)}>
      <button className="self-check-head" onClick={() => setOpen((value) => !value)}>
        <ShieldCheck size={13} />
        <strong>证据自检</strong>
        <Badge tone={tone}>{check.status === "pass" ? "通过" : check.status === "fail" ? "需重做" : "有风险"}</Badge>
        <span>{check.score}/100</span>
        <ChevronDown size={13} className={cn(open && "rotate-180")} />
      </button>
      {open && (
        <div className="self-check-body">
          <p>{check.summary}</p>
          {check.issues.length > 0 && <ul>{check.issues.map((item) => <li key={item} className="self-issue">{item}</li>)}</ul>}
          {check.warnings.length > 0 && <ul>{check.warnings.map((item) => <li key={item}>{item}</li>)}</ul>}
          {check.failed_steps.length > 0 && (
            <div className="self-failed">
              {check.failed_steps.map((step) => <span key={step.index}>步骤 {step.index} · {step.tool || "工具"}：{truncate(step.error, 80)}</span>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function stripMarkdown(text: string): string {
  return text
    .replace(/[#>*_`|]/g, " ")
    .replace(/\[(C\d+)\]/g, "[$1]")
    .replace(/\s+/g, " ")
    .trim();
}

function AgentTimeline({ steps }: { steps: AgentStep[] }) {
  const [open, setOpen] = useState(steps.length <= 3);
  const running = steps.some((step) => step.status === "running");
  return (
    <div className={cn("timeline", running && "timeline-running")}>
      <button className="timeline-head" onClick={() => setOpen((value) => !value)}>
        <Wrench size={13} />
        <span>
          智能体执行过程 · {steps.length} 步
          {running ? "（进行中）" : ""}
        </span>
        <ChevronDown size={13} className={cn(open && "rotate-180")} />
      </button>
      {open && (
        <ol className="timeline-list">
          {steps.map((step) => (
            <li key={step.index} className={cn("timeline-step", "step-" + step.status)}>
              <span className="step-dot">
                {step.status === "running" ? <Loader2 size={11} className="spin" /> : step.status === "error" ? <X size={11} /> : <Check size={11} />}
              </span>
              <div>
                <strong>{step.label}</strong>
                {step.summary && <p>{truncate(stripMarkdown(step.summary), 130)}</p>}
                {step.duration_ms ? <small>{step.duration_ms}ms</small> : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function SourceCard({ citation, onOpen }: { citation: Citation; onOpen: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="source-card">
      <div className="source-head">
        <span className="source-key">{citation.key}</span>
        <button className="source-title" onClick={onOpen} title={citation.paper_title}>
          {truncate(citation.paper_title, 64)}
        </button>
        <span className="source-page">p.{citation.page}</span>
      </div>
      <p className={cn("source-quote", expanded && "source-quote-open")}>{citation.quote}</p>
      <div className="source-foot">
        <span>{truncate(citation.section || "正文", 40)}</span>
        <div>
          {citation.quote.length > 220 && (
            <button onClick={() => setExpanded((value) => !value)}>{expanded ? "收起" : "展开"}</button>
          )}
          <button onClick={onOpen}>
            <ExternalLink size={12} /> 原文
          </button>
        </div>
      </div>
    </div>
  );
}

function ActionCard({ action, onDone }: { action: PendingAction; onDone?: () => void }) {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [state, setState] = useState<"pending" | "running" | "done" | "error">("pending");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  async function confirm() {
    setState("running");
    try {
      const response = await api<{ result: { data: Record<string, unknown>; summary: string } }>("/agent/actions/confirm", {
        method: "POST",
        body: { tool: action.tool, args: action.args },
      });
      setResult(response.result.data);
      setState("done");
      onDone?.();
      toast(response.result.summary || "已执行", "success");
    } catch (error) {
      setState("error");
      toast((error as Error).message || "操作失败", "error");
    }
  }

  const downloadUrl = result?.download_url as string | undefined;
  const previewText =
    action.tool === "save_knowledge"
      ? String(action.args.title || "") + " — " + String(action.args.content || "")
      : String(action.preview || action.args.title || action.args.quote || "");

  return (
    <div className={cn("action-card", "action-" + state)}>
      <div className="action-head">
        {action.tool === "export_document" ? <Save size={15} /> : <BookmarkPlus size={15} />}
        <div>
          <strong>{action.label}</strong>
          <p>{truncate(stripMarkdown(previewText), 150)}</p>
        </div>
        <Badge tone={state === "done" ? "accent" : "warn"}>{state === "done" ? "已执行" : "待确认"}</Badge>
      </div>
      <div className="action-buttons">
        {state === "done" ? (
          <>
            {action.tool === "save_knowledge" && (
              <Button size="sm" variant="soft" onClick={() => navigate("/app/knowledge")}>
                查看知识库
              </Button>
            )}
            {downloadUrl && (
              <Button
                size="sm"
                variant="soft"
                onClick={async () => {
                  const { downloadFile } = await import("../lib/api");
                  await downloadFile(downloadUrl, String(result?.filename || "paperlens-export"));
                }}
              >
                下载文件
              </Button>
            )}
          </>
        ) : (
          <>
            <Button size="sm" variant="primary" onClick={confirm} loading={state === "running"}>
              确认并执行
            </Button>
            <span className="muted small">写入前需要你的明确同意</span>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ composer */

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  mode,
  onModeChange,
  scope,
  onScopeClick,
  onUploaded,
  placeholder = "针对你的论文提问，例如：这篇论文的方法在哪些数据集上验证过？",
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  mode: string;
  onModeChange: (mode: string) => void;
  scope: ScopeSelection;
  onScopeClick: () => void;
  onUploaded?: () => void;
  placeholder?: string;
}) {
  const { toast } = useApp();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [modeOpen, setModeOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const activeMode = MODES.find((item) => item.id === mode) || MODES[0];

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 220) + "px";
  }, [value]);

  function submit() {
    if (streaming) return;
    if (!value.trim()) return;
    onSend();
  }

  return (
    <div className="composer">
      <div className="composer-top">
        <button className="scope-pill" onClick={onScopeClick}>
          <FileText size={13} />
          {scope.label}
          <ChevronDown size={12} />
        </button>
        <div className="mode-picker">
          <button className="mode-pill" onClick={() => setModeOpen((open) => !open)}>
            <span className="mode-dot" />
            {activeMode.label}
            <ChevronDown size={12} />
          </button>
          {modeOpen && (
            <div className="mode-menu">
              {MODES.map((item) => (
                <button
                  key={item.id}
                  className={cn("mode-option", item.id === mode && "mode-option-active")}
                  onClick={() => {
                    onModeChange(item.id);
                    setModeOpen(false);
                  }}
                >
                  <strong>{item.label}</strong>
                  <span>{item.hint}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {streaming && <span className="composer-live">正在生成…</span>}
      </div>

      <div className="composer-box">
        <textarea
          ref={textareaRef}
          value={value}
          rows={1}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const file = event.dataTransfer.files?.[0];
            if (file) {
              void handleAttach(file);
            }
          }}
        />
        <div className="composer-controls">
          <div className="composer-left">
            <IconButton label="上传论文" onClick={() => setAttachOpen(true)} disabled={uploading}>
              {uploading ? <Loader2 size={16} className="spin" /> : <Paperclip size={16} />}
            </IconButton>
            <span className="composer-hint">Enter 发送 · Shift+Enter 换行</span>
          </div>
          <div className="composer-right">
            {streaming ? (
              <Button variant="secondary" size="sm" icon={<CircleStop size={14} />} onClick={onStop}>
                停止
              </Button>
            ) : (
              <Button variant="primary" size="sm" onClick={submit} disabled={!value.trim()} icon={<ArrowUp size={15} />}>
                发送
              </Button>
            )}
          </div>
        </div>
      </div>

      {attachOpen && (
        <div className="attach-popover">
          <div className="attach-head">
            <strong>上传论文到当前研究</strong>
            <IconButton label="关闭" onClick={() => setAttachOpen(false)}>
              <X size={15} />
            </IconButton>
          </div>
          <Uploader
            compact
            onUploaded={(paper) => {
              setAttachOpen(false);
              onChange((value ? value + " " : "") + "请阅读刚上传的《" + paper.title + "》并总结其核心贡献。");
              onUploaded?.();
            }}
          />
        </div>
      )}
    </div>
  );

  async function handleAttach(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast("请拖入 PDF 文件", "error");
      return;
    }
    setUploading(true);
    try {
      const paper = await uploadPdf(file);
      if (paper.status === "failed") {
        toast("论文解析失败", "error", paper.error || undefined);
        return;
      }
      onChange((value ? value + " " : "") + "请阅读刚上传的《" + paper.title + "》并总结其核心贡献。");
      onUploaded?.();
      toast("论文已加入研究范围", "success", paper.title.slice(0, 40));
    } catch (error) {
      const detail = (error as { detail?: { code?: string; message?: string } }).detail;
      if (detail?.code === "duplicate") {
        toast("这篇论文已在资料库中", "info");
      } else {
        toast((error as Error).message || "上传失败", "error");
      }
    } finally {
      setUploading(false);
    }
  }
}

/* ------------------------------------------------------------------ empty state */

export function ChatEmpty({
  onSuggestion,
  hasPapers,
  onOpenLibrary,
}: {
  onSuggestion: (text: string) => void;
  hasPapers: boolean;
  onOpenLibrary: () => void;
}) {
  const suggestions = hasPapers
    ? [
        "用三句话概括资料库中最新的论文，并给出页码引用",
        "这些论文在实验设计上有哪些主要差异？",
        "哪篇论文的方法最值得复现？有哪些潜在陷阱？",
        "基于我的资料库，指出一个可验证的研究缺口",
      ]
    : [
        "上传第一篇论文后，我可以帮你逐段精读",
        "支持多论文对比、研究缺口分析与知识保存",
        "所有回答都会附带页码与原文引用",
      ];
  return (
    <div className="chat-empty">
      <div className="chat-empty-mark">
        <Sparkles size={22} />
      </div>
      <h2>从一个具体的研究问题开始</h2>
      <p>
        {hasPapers
          ? "PaperLens 会检索你的论文，先找证据，再回答。每个结论都能回到原文。"
          : "资料库还是空的。上传一篇 PDF，PaperLens 会解析章节、图表与页码坐标。"}
      </p>
      <div className="suggestion-grid">
        {suggestions.map((suggestion) => (
          <button key={suggestion} onClick={() => (hasPapers ? onSuggestion(suggestion) : onOpenLibrary())}>
            <ChevronRight size={14} />
            {suggestion}
          </button>
        ))}
      </div>
      {!hasPapers && (
        <Button variant="primary" onClick={onOpenLibrary} icon={<FileText size={15} />}>
          上传第一篇论文
        </Button>
      )}
    </div>
  );
}