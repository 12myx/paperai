import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Clock, MessageSquare, Search, Trash2 } from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type { Conversation } from "../lib/types";
import { truncate } from "../lib/utils";
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, Input, Modal } from "../components/ui";

const MODE_LABEL: Record<string, string> = {
  quick: "快速问答", deep_read: "深度阅读", multi_paper: "多论文", critical: "批判性分析", explore: "研究探索",
};

export function History() {
  const { toast } = useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [toDelete, setToDelete] = useState<Conversation | null>(null);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [title, setTitle] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api<{ items: Conversation[] }>("/conversations?limit=100" + (query ? "&query=" + encodeURIComponent(query) : ""));
      setItems(response.items);
    } catch {
      toast("无法加载历史记录", "error");
    } finally {
      setLoading(false);
    }
  }, [query, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove() {
    if (!toDelete) return;
    try {
      await api("/conversations/" + toDelete.id, { method: "DELETE" });
      setItems((current) => current.filter((item) => item.id !== toDelete.id));
      setToDelete(null);
      toast("对话已删除", "success");
    } catch {
      toast("删除失败", "error");
    }
  }

  async function rename() {
    if (!renaming) return;
    try {
      await api("/conversations/" + renaming.id, { method: "PATCH", body: { title } });
      setItems((current) => current.map((item) => (item.id === renaming.id ? { ...item, title } : item)));
      setRenaming(null);
      toast("标题已更新", "success");
    } catch {
      toast("重命名失败", "error");
    }
  }

  return (
    <div className="page page-history">
      <header className="page-head">
        <div>
          <span className="eyebrow">Research history</span>
          <h1>历史记录</h1>
          <p>{items.length} 段研究对话 · 打开即可继续追问，所有引用与结论都保留</p>
        </div>
        <div className="filter-search" style={{ maxWidth: 300 }}>
          <Search size={16} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索对话标题" />
        </div>
      </header>

      {loading ? (
        <div className="history-list">{[0, 1, 2].map((index) => <div key={index} className="skeleton" style={{ height: 82 }} />)}</div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<MessageSquare size={26} />}
          title="还没有研究记录"
          description="每次向 AI 提问都会保存为一段对话，包含完整的证据引用。"
          action={<Button variant="primary" onClick={() => navigate("/app")}>开始第一次提问</Button>}
        />
      ) : (
        <div className="history-list">
          {items.map((conversation) => (
            <div key={conversation.id} className="history-item">
              <button className="history-main" onClick={() => navigate("/app?conversation=" + conversation.id)}>
                <span className="history-icon"><Clock size={16} /></span>
                <div>
                  <div className="history-title-line">
                    <strong>{truncate(conversation.title, 70)}</strong>
                    <Badge tone="neutral">{MODE_LABEL[conversation.mode] || conversation.mode}</Badge>
                    <Badge tone="info">{conversation.message_count} 条</Badge>
                  </div>
                  {conversation.preview && <p>{truncate(conversation.preview, 150)}</p>}
                  <span className="history-time">{new Date(conversation.updated_at).toLocaleString("zh-CN")} · {conversation.scope_type === "all" ? "全部资料库" : conversation.scope_type}</span>
                </div>
                <ArrowRight size={15} className="history-arrow" />
              </button>
              <div className="history-actions">
                <IconButton label="重命名" onClick={() => { setRenaming(conversation); setTitle(conversation.title); }}>
                  <span className="text-icon">Aa</span>
                </IconButton>
                <IconButton label="删除" onClick={() => setToDelete(conversation)}>
                  <Trash2 size={14} />
                </IconButton>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除这段对话？"
        description="消息与引用会被删除，知识库中已保存的内容不受影响。"
        confirmLabel="删除"
        danger
        onConfirm={() => void remove()}
        onClose={() => setToDelete(null)}
      />

      <Modal
        open={Boolean(renaming)}
        onClose={() => setRenaming(null)}
        title="重命名对话"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRenaming(null)}>取消</Button>
            <Button variant="primary" onClick={() => void rename()}>保存</Button>
          </>
        }
      >
        <Input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus />
      </Modal>
    </div>
  );
}
