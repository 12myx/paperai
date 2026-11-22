import { useEffect, useMemo, useState } from "react";
import { Check, FileText, Search } from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import type { Collection, Paper } from "../lib/types";
import { cn, truncate } from "../lib/utils";
import { Button, Input, Modal, Tabs } from "./ui";

export function PaperPicker({
  open,
  onClose,
  onConfirm,
  initialIds = [],
  title = "选择研究范围",
  description = "AI 只会基于你选择的论文作答，并给出可追溯的引用。",
  multi = true,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (ids: string[], papers: Paper[]) => void;
  initialIds?: string[];
  title?: string;
  description?: string;
  multi?: boolean;
}) {
  const { toast } = useApp();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selected, setSelected] = useState<string[]>(initialIds);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("papers");
  const initialKey = initialIds.join("|");

  useEffect(() => {
    if (!open) return;
    setSelected(initialIds);
    setLoading(true);
    Promise.all([
      api<{ items: Paper[] }>("/papers?limit=200&status=ready"),
      api<{ items: Collection[] }>("/collections"),
    ])
      .then(([paperResponse, collectionResponse]) => {
        setPapers(paperResponse.items);
        setCollections(collectionResponse.items);
      })
      .catch(() => toast("无法加载论文列表", "error"))
      .finally(() => setLoading(false));
  }, [open, initialKey, toast]);

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
    setSelected((current) => {
      if (!multi) return [id];
      return current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={description}
      size="lg"
      footer={
        <>
          <span className="muted small" style={{ marginRight: "auto" }}>
            已选择 {selected.length} 篇
          </span>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            disabled={selected.length === 0}
            onClick={() => {
              onConfirm(selected, papers.filter((paper) => selected.includes(paper.id)));
              onClose();
            }}
          >
            使用这些论文
          </Button>
        </>
      }
    >
      <Tabs
        items={[
          { id: "papers", label: "全部论文", count: papers.length },
          { id: "collections", label: "合集", count: collections.length },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "papers" ? (
        <>
          <div className="picker-search">
            <Search size={15} />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按标题、作者或摘要搜索" />
          </div>
          <div className="picker-list">
            {loading && <p className="muted">加载中…</p>}
            {!loading && filtered.length === 0 && (
              <p className="muted">还没有解析完成的论文。先上传一篇 PDF 吧。</p>
            )}
            {filtered.map((paper) => (
              <button
                key={paper.id}
                className={cn("picker-item", selected.includes(paper.id) && "picker-selected")}
                onClick={() => toggle(paper.id)}
              >
                <span className="picker-check">{selected.includes(paper.id) && <Check size={13} />}</span>
                <span className="picker-file">
                  <FileText size={15} />
                </span>
                <span className="picker-meta">
                  <strong>{truncate(paper.title, 90)}</strong>
                  <small>
                    {paper.authors ? truncate(paper.authors, 60) + " · " : ""}
                    {paper.year || "n.d."} · {paper.page_count} 页
                  </small>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="picker-list">
          {collections.length === 0 && <p className="muted">还没有合集。可以先在论文库中创建合集。</p>}
          {collections.map((collection) => (
            <button
              key={collection.id}
              className="picker-item collection-item"
              onClick={async () => {
                try {
                  const response = await api<{ items: Paper[] }>("/papers?collection_id=" + collection.id + "&limit=200");
                  const ids = response.items.filter((p) => p.status === "ready").map((p) => p.id);
                  if (ids.length === 0) {
                    toast("该合集中没有已解析的论文", "info");
                    return;
                  }
                  setSelected(ids);
                  onConfirm(ids, response.items.filter((p) => ids.includes(p.id)));
                  onClose();
                } catch {
                  toast("无法加载合集", "error");
                }
              }}
            >
              <span className="picker-file">
                <FileText size={15} />
              </span>
              <span className="picker-meta">
                <strong>{collection.name}</strong>
                <small>{collection.paper_count} 篇论文 · {collection.description || "无描述"}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}