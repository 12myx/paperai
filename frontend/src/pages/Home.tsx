import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookMarked,
  FileText,
  FolderKanban,
  Layers,
  Loader2,
  MessageSquarePlus,
  Plus,
  Sparkles,
  StickyNote,
  Upload,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type { Conversation, Paper, ScopeSelection, Stats } from "../lib/types";
import { cn, MODES, relativeTime, truncate } from "../lib/utils";
import { Badge, Button, Card, IconButton } from "../components/ui";
import { ChatEmpty, ChatMessageItem, Composer, useChat } from "../components/Chat";
import { PaperPicker } from "../components/PaperPicker";
import { Uploader } from "../components/Uploader";

export function Home() {
  const { user, model, toast } = useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState("quick");
  const [scope, setScope] = useState<ScopeSelection>({ type: "all", ids: [], label: "全部资料库" });
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const initialConversation = searchParams.get("conversation");

  const { messages, streaming, paused, send, stop, reset, conversationId, loadConversation, executePlan, updatePlan, pause, resume, cancel } = useChat({
    mode,
    scope,
    onConversation: (id) => {
      const params = new URLSearchParams(searchParams);
      params.set("conversation", id);
      setSearchParams(params, { replace: true });
    },
  });

  const refreshLibrary = useCallback(async () => {
    try {
      const [paperResponse, statResponse, conversationResponse] = await Promise.all([
        api<{ items: Paper[] }>("/papers?limit=40"),
        api<Stats>("/library/stats"),
        api<{ items: Conversation[] }>("/conversations?limit=6"),
      ]);
      setPapers(paperResponse.items);
      setStats(statResponse);
      setConversations(conversationResponse.items);
    } catch {
      // the workspace still renders with empty state on transient errors
    }
  }, []);

  useEffect(() => {
    void refreshLibrary();
  }, [refreshLibrary]);

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      reset();
      const params = new URLSearchParams(searchParams);
      params.delete("new");
      setSearchParams(params, { replace: true });
    }
  }, [searchParams, reset, setSearchParams]);

  useEffect(() => {
    if (!initialConversation) return;
    if (initialConversation === conversationId) return;
    void loadConversation(initialConversation);
  }, [initialConversation, conversationId, loadConversation]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const readyPapers = useMemo(() => papers.filter((paper) => paper.status === "ready"), [papers]);

  useEffect(() => {
    if (scope.type === "all" && (scope.label === "全部资料库" || scope.label.startsWith("全部资料库"))) {
      setScope((current) => ({ ...current, label: "全部资料库 · " + readyPapers.length + " 篇" }));
    }
  }, [readyPapers.length, scope.type, scope.label]);

  const greeting = (() => {
    const hour = new Date().getHours();
    if (hour < 6) return "夜深了";
    if (hour < 12) return "早上好";
    if (hour < 18) return "下午好";
    return "晚上好";
  })();

  const modeMeta = MODES.find((item) => item.id === mode) || MODES[0];

  function submit(text?: string) {
    const value = (text ?? draft).trim();
    if (!value || streaming) return;
    setDraft("");
    void send(value);
  }

  function regenerate() {
    const lastUser = [...messages].reverse().find((message) => message.role === "user");
    if (!lastUser) return;
    void send(lastUser.content, { regenerate: true });
  }

  return (
    <div className="page page-home">
      <div className="home-grid">
        <section className="home-main">
          <header className="home-head">
            <div>
              <span className="eyebrow">
                <Sparkles size={13} /> Research Agent
              </span>
              <h1>
                {greeting}，{user?.display_name?.split(" ")[0] || "研究者"}
              </h1>
              <p>
                {readyPapers.length > 0
                  ? "你的资料库中有 " + readyPapers.length + " 篇可检索论文。先提问，PaperLens 会找到证据再回答。"
                  : "资料库还是空的。上传一篇论文，开始一段可追溯的阅读。"}
              </p>
            </div>
            <div className="home-head-actions">
              <Button
                variant="secondary"
                size="sm"
                icon={<Upload size={15} />}
                onClick={() => setUploadOpen((open) => !open)}
              >
                导入论文
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<MessageSquarePlus size={15} />}
                onClick={() => {
                  reset();
                  setSearchParams({}, { replace: true });
                  setDraft("");
                }}
              >
                新对话
              </Button>
            </div>
          </header>

          {uploadOpen && (
            <div className="home-upload">
              <Uploader
                compact
                onUploaded={() => {
                  setUploadOpen(false);
                  void refreshLibrary();
                }}
              />
            </div>
          )}

          <div className={cn("chat-area", messages.length === 0 && "chat-area-empty")}>
            {messages.length === 0 ? (
              <ChatEmpty onSuggestion={submit} hasPapers={readyPapers.length > 0} onOpenLibrary={() => setUploadOpen(true)} />
            ) : (
              <div className="chat-scroll">
                <div className="chat-thread">
                  {messages.map((message) => (
                    <ChatMessageItem
                      key={message.id}
                      message={message}
                      onRegenerate={regenerate}
                      showRegenerate={!streaming}
                      onExecutePlan={(messageId, taskId) => void executePlan(messageId, taskId)}
                      onPausePlan={(taskId) => void pause(taskId)}
                      onResumePlan={(taskId) => void resume(taskId)}
                      onCancelPlan={(messageId, taskId) => void cancel(messageId, taskId)}
                      onUpdatePlan={(messageId, taskId, plan) => void updatePlan(messageId, taskId, plan)}
                    />
                  ))}
                  <div ref={bottomRef} />
                </div>
              </div>
            )}
          </div>

          <div className="chat-compose">
            <Composer
              value={draft}
              onChange={setDraft}
              onSend={() => submit()}
              onStop={stop}
              streaming={streaming}
              mode={mode}
              onModeChange={setMode}
              scope={scope}
              onScopeClick={() => setPickerOpen(true)}
              onUploaded={() => void refreshLibrary()}
            />
            <p className="composer-disclaimer">
              {model?.configured
                ? "回答基于你资料库中的论文原文生成，并附带引用；请核对原文后再引用到自己的工作中。"
                : "当前为本地抽取模式：回答由真实检索片段组成，不做生成式改写。配置模型后可获得生成式分析与翻译。"}
            </p>
          </div>
        </section>

        <aside className="home-rail">
          <Card className="rail-card">
            <div className="rail-card-head">
              <span>研究上下文</span>
              <Badge tone={model?.configured ? "accent" : "warn"}>{model?.configured ? "生成式" : "本地抽取"}</Badge>
            </div>
            <div className="context-mode">
              <strong>{modeMeta.label}</strong>
              <span>{modeMeta.hint}</span>
            </div>
            <div className="context-scope">
              <span>研究范围</span>
              <button onClick={() => setPickerOpen(true)}>
                {scope.label}
                <ArrowRight size={13} />
              </button>
            </div>
            {scope.type === "papers" && scope.ids.length > 0 && (
              <ul className="context-papers">
                {scope.papers?.slice(0, 3).map((paper) => (
                  <li key={paper.id}>{truncate(paper.title, 42)}</li>
                ))}
                {scope.ids.length > 3 && <li className="muted">还有 {scope.ids.length - 3} 篇…</li>}
              </ul>
            )}
          </Card>

          <Card className="rail-card">
            <div className="rail-card-head">
              <span>最近论文</span>
              <button className="link-btn" onClick={() => navigate("/app/papers")}>
                全部
              </button>
            </div>
            {papers.length === 0 ? (
              <p className="rail-empty">还没有论文。上传 PDF 后将自动解析章节与图表。</p>
            ) : (
              <ul className="rail-papers">
                {papers.slice(0, 4).map((paper) => (
                  <li key={paper.id}>
                    <button onClick={() => navigate("/app/papers/" + paper.id)}>
                      <span className="rail-paper-icon">
                        {paper.status === "processing" ? <Loader2 size={14} className="spin" /> : <FileText size={14} />}
                      </span>
                      <span className="rail-paper-meta">
                        <strong>{truncate(paper.title, 52)}</strong>
                        <small>
                          {paper.year || "n.d."} · {paper.page_count ? paper.page_count + " 页" : "解析中"}
                        </small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="rail-stats">
            {[
              { label: "论文", value: stats?.papers ?? 0, icon: FileText },
              { label: "批注", value: stats?.annotations ?? 0, icon: StickyNote },
              { label: "知识", value: stats?.knowledge ?? 0, icon: BookMarked },
              { label: "项目", value: stats?.projects ?? 0, icon: FolderKanban },
            ].map((item) => (
              <Card key={item.label} className="stat-tile">
                <item.icon size={15} />
                <strong>{item.value}</strong>
                <span>{item.label}</span>
              </Card>
            ))}
          </div>

          {conversations.length > 0 && (
            <Card className="rail-card">
              <div className="rail-card-head">
                <span>继续上次研究</span>
                <button className="link-btn" onClick={() => navigate("/app/history")}>
                  历史
                </button>
              </div>
              <ul className="rail-history">
                {conversations.slice(0, 3).map((conversation) => (
                  <li key={conversation.id}>
                    <button onClick={() => navigate("/app?conversation=" + conversation.id)}>
                      <span>{truncate(conversation.title, 46)}</span>
                      <small>{relativeTime(conversation.updated_at)}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="rail-card rail-actions">
            <button onClick={() => navigate("/app/research")}>
              <Layers size={16} />
              <span>
                <strong>多论文对比</strong>
                <small>方法与实验横向比较</small>
              </span>
              <ArrowRight size={14} />
            </button>
            <button onClick={() => navigate("/app/research?tab=gap")}>
              <Sparkles size={16} />
              <span>
                <strong>发现研究缺口</strong>
                <small>基于资料库的证据线索</small>
              </span>
              <ArrowRight size={14} />
            </button>
            <button onClick={() => navigate("/app/knowledge")}>
              <BookMarked size={16} />
              <span>
                <strong>整理知识库</strong>
                <small>让结论沉淀下来</small>
              </span>
              <ArrowRight size={14} />
            </button>
          </Card>
        </aside>
      </div>

      <PaperPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        initialIds={scope.type === "papers" ? scope.ids : []}
        onConfirm={(ids, selectedPapers) => {
          if (ids.length === 0) {
            setScope({ type: "all", ids: [], label: "全部资料库 · " + readyPapers.length + " 篇" });
          } else {
            setScope({
              type: "papers",
              ids,
              label: ids.length === 1 ? "《" + truncate(selectedPapers[0]?.title || "", 26) + "》" : ids.length + " 篇论文",
              papers: selectedPapers,
            });
          }
          toast("研究范围已更新", "success");
        }}
      />

      <button className="fab-new" onClick={() => { reset(); setSearchParams({}, { replace: true }); }}>
        <Plus size={18} />
      </button>
    </div>
  );
}