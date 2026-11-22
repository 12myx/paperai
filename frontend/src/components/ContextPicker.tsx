import { useEffect, useMemo, useState, type ReactNode } from "react";
import { BookMarked, Image as ImageIcon, Loader2, ScrollText, Search } from "lucide-react";
import { api } from "../lib/api";
import type { AcademicArtifact, Figure, KnowledgeItem } from "../lib/types";
import { Button, Input, Modal } from "./ui";

export interface SelectedResources {
  knowledge_ids: string[];
  image_ids: string[];
  artifact_ids: string[];
  exclude_ids: string[];
}

export const EMPTY_RESOURCES: SelectedResources = { knowledge_ids: [], image_ids: [], artifact_ids: [], exclude_ids: [] };

export function ContextPicker({
  open,
  selected,
  onClose,
  onApply,
}: {
  open: boolean;
  selected: SelectedResources;
  onClose: () => void;
  onApply: (next: SelectedResources) => void;
}) {
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([]);
  const [figures, setFigures] = useState<Figure[]>([]);
  const [artifacts, setArtifacts] = useState<AcademicArtifact[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState<SelectedResources>(selected);
  const [excludeMode, setExcludeMode] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDraft(selected);
    setQuery("");
    setLoading(true);
    Promise.all([
      api<{ items: KnowledgeItem[] }>("/knowledge?limit=100"),
      api<{ items: Figure[] }>("/figures?limit=100"),
      api<{ items: AcademicArtifact[] }>("/artifacts?limit=50"),
    ])
      .then(([k, f, a]) => {
        setKnowledge(k.items);
        setFigures(f.items);
        setArtifacts(a.items);
      })
      .catch(() => {
        setKnowledge([]);
        setFigures([]);
        setArtifacts([]);
      })
      .finally(() => setLoading(false));
  }, [open, selected]);

  const needle = query.trim().toLowerCase();
  const knowledgeRows = useMemo(
    () => knowledge.filter((item) => !needle || (item.title + " " + item.content).toLowerCase().includes(needle)).slice(0, 40),
    [knowledge, needle],
  );
  const figureRows = useMemo(
    () => figures.filter((item) => !needle || ((item.caption || "") + " " + (item.paper_title || "")).toLowerCase().includes(needle)).slice(0, 30),
    [figures, needle],
  );
  const artifactRows = useMemo(
    () => artifacts.filter((item) => !needle || (item.title + " " + item.kind).toLowerCase().includes(needle)).slice(0, 30),
    [artifacts, needle],
  );

  type ResourceKey = "knowledge_ids" | "image_ids" | "artifact_ids";
  function toggle(kind: ResourceKey, id: string) {
    setDraft((current) => {
      if (excludeMode) {
        return {
          ...current,
          [kind]: current[kind].filter((item) => item !== id),
          exclude_ids: current.exclude_ids.includes(id)
            ? current.exclude_ids.filter((item) => item !== id)
            : [...current.exclude_ids, id],
        };
      }
      return {
        ...current,
        [kind]: current[kind].includes(id) ? current[kind].filter((item) => item !== id) : [...current[kind], id],
        exclude_ids: current.exclude_ids.filter((item) => item !== id),
      };
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="选择本次研究资料"
      subtitle="显式选择的资料优先于自动检索；未选择的资料仍可由 Agent 按需检索。"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => setDraft(EMPTY_RESOURCES)}>清空</Button>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="primary" onClick={() => { onApply(draft); onClose(); }}>应用上下文</Button>
        </>
      }
    >
      <div className="context-picker">
        <div className="context-picker-toolbar">
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索知识、图片、成果…" />
          <button
            className={"context-exclude-toggle " + (excludeMode ? "active" : "")}
            onClick={() => setExcludeMode((value) => !value)}
          >
            {excludeMode ? "排除模式：开" : "排除模式：关"}
          </button>
        </div>
        {excludeMode && <p className="context-picker-hint">当前勾选会加入排除列表；被排除的资料不会被自动检索或工具读取。</p>}
        {loading ? (
          <div className="context-picker-loading"><Loader2 size={16} className="spin" /> 正在加载研究资料…</div>
        ) : (
          <div className="context-picker-groups">
            <ContextGroup
              icon={<BookMarked size={14} />} title="个人知识" count={draft.knowledge_ids.length}
              empty="没有知识条目"
              rows={knowledgeRows.map((item) => ({ id: item.id, label: item.title, detail: item.kind }))}
              selected={draft.knowledge_ids}
              excluded={draft.exclude_ids}
              excludeMode={excludeMode}
              onToggle={(id) => toggle("knowledge_ids", id)}
            />
            <ContextGroup
              icon={<ImageIcon size={14} />} title="图像 / 图表" count={draft.image_ids.length}
              empty="没有图像"
              rows={figureRows.map((item) => ({ id: item.id, label: item.caption || item.kind, detail: item.paper_title || "" }))}
              selected={draft.image_ids}
              excluded={draft.exclude_ids}
              excludeMode={excludeMode}
              onToggle={(id) => toggle("image_ids", id)}
            />
            <ContextGroup
              icon={<ScrollText size={14} />} title="学术成果" count={draft.artifact_ids.length}
              empty="没有成果"
              rows={artifactRows.map((item) => ({ id: item.id, label: item.title, detail: item.kind }))}
              selected={draft.artifact_ids}
              excluded={draft.exclude_ids}
              excludeMode={excludeMode}
              onToggle={(id) => toggle("artifact_ids", id)}
            />
          </div>
        )}
      </div>
    </Modal>
  );
}

function ContextGroup({
  icon, title, count, rows, selected, excluded, excludeMode, onToggle, empty,
}: {
  icon: ReactNode;
  title: string;
  count: number;
  rows: { id: string; label: string; detail?: string }[];
  selected: string[];
  excluded: string[];
  excludeMode: boolean;
  onToggle: (id: string) => void;
  empty: string;
}) {
  return (
    <section className="context-picker-group">
      <header>{icon}<strong>{title}</strong><span>{count ? "已选 " + count : ""}</span></header>
      {rows.length === 0 ? <p className="muted small">{empty}</p> : (
        <div className="context-picker-rows">
          {rows.map((row) => (
            <label key={row.id} className={"context-picker-row " + (selected.includes(row.id) ? "selected " : "") + (excluded.includes(row.id) ? "excluded" : "")}>
              <input type="checkbox" checked={excludeMode ? excluded.includes(row.id) : selected.includes(row.id)} onChange={() => onToggle(row.id)} />
              <span><strong>{row.label}</strong>{row.detail && <small>{row.detail}</small>}</span>
            </label>
          ))}
        </div>
      )}
    </section>
  );
}