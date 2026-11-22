import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CloudUpload, FileText, FileUp, Loader2, RotateCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../store/AppContext";
import { api, ApiError, authHeaders, getToken } from "../lib/api";
import { notifyUsageChanged, UPLOAD_RESULT_EVENT } from "../lib/events";
import { formatBytes } from "../lib/utils";
import { Button, Modal } from "./ui";
import type { Paper } from "../lib/types";

type Phase = "waiting" | "uploading" | "parsing" | "done" | "error" | "duplicate" | "skipped";

interface UploadItem {
  id: string;
  file: File;
  phase: Phase;
  progress: number;
  paper?: Paper;
  error?: string;
}

export interface UploadResultItem {
  filename: string;
  status: "success" | "failed" | "skipped";
  reason?: string;
  paperId?: string;
}

export interface UploadBatchResult {
  at: number;
  success: number;
  failed: number;
  skipped: number;
  items: UploadResultItem[];
}

export const UPLOAD_RESULT_KEY = "paperlens.upload.lastResult";

function safeReason(message: string | null | undefined, fallback: string): string {
  const cleaned = String(message || "")
    .replace(/[A-Za-z]:\\[^\s"'<>]+/g, "[本地路径]")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 220);
  return cleaned || fallback;
}

function buildResult(items: UploadItem[]): UploadBatchResult {
  const rows: UploadResultItem[] = items.map((item) => {
    if (item.phase === "done") {
      return { filename: item.file.name, status: "success", paperId: item.paper?.id };
    }
    if (item.phase === "error") {
      return {
        filename: item.file.name,
        status: "failed",
        reason: safeReason(item.error, "解析失败"),
        paperId: item.paper?.id,
      };
    }
    return {
      filename: item.file.name,
      status: "skipped",
      reason: safeReason(item.error, "已跳过"),
      paperId: item.paper?.id,
    };
  });
  return {
    at: Date.now(),
    success: rows.filter((row) => row.status === "success").length,
    failed: rows.filter((row) => row.status === "failed").length,
    skipped: rows.filter((row) => row.status === "skipped").length,
    items: rows,
  };
}

function persistResult(result: UploadBatchResult): void {
  try {
    localStorage.setItem(UPLOAD_RESULT_KEY, JSON.stringify(result));
  } catch {
    // storage can be unavailable in private mode; the in-memory result still works
  }
  window.dispatchEvent(new CustomEvent(UPLOAD_RESULT_EVENT, { detail: result }));
}

function readResult(): UploadBatchResult | null {
  try {
    const raw = localStorage.getItem(UPLOAD_RESULT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as UploadBatchResult;
    if (!parsed || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function uploadWithProgress(
  file: File,
  options: { tags?: string; collectionId?: string; allowDuplicate?: boolean },
  onProgress: (percent: number) => void,
): Promise<{ paper: Paper }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    if (options.tags) form.append("tags", options.tags);
    if (options.collectionId) form.append("collection_id", options.collectionId);
    if (options.allowDuplicate) form.append("allow_duplicate", "true");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/papers");
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as { paper: Paper });
        return;
      }
      const detail = (payload as { detail?: unknown })?.detail;
      reject(new ApiError(xhr.status, typeof detail === "string" ? detail : (detail as { message?: string })?.message || "上传失败", detail));
    };
    xhr.onerror = () => reject(new Error("网络错误，上传失败"));
    xhr.send(form);
  });
}

async function waitForReady(paperId: string, onTick: (paper: Paper) => void): Promise<Paper> {
  // The backend queue is intentionally serial. Allow enough time for several
  // large PDFs without falsely reporting a timeout in the multi-upload flow.
  for (let attempt = 0; attempt < 400; attempt += 1) {
    const response = await fetch("/api/papers/" + paperId, { headers: authHeaders() });
    if (response.ok) {
      const paper = (await response.json()) as Paper;
      onTick(paper);
      if (paper.status === "ready" || paper.status === "failed") return paper;
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error("解析超时，请稍后在论文库中查看处理状态");
}

async function mapLimit<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const item = items[cursor];
      cursor += 1;
      await worker(item);
    }
  });
  await Promise.all(runners);
}

export function Uploader({
  collectionId,
  onUploaded,
  onBatchUploaded,
  compact = false,
  autoNavigate = false,
}: {
  collectionId?: string;
  onUploaded?: (paper: Paper) => void;
  onBatchUploaded?: (papers: Paper[]) => void;
  compact?: boolean;
  autoNavigate?: boolean;
}) {
  const { toast } = useApp();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const itemsRef = useRef<UploadItem[]>([]);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [summary, setSummary] = useState<UploadBatchResult | null>(null);
  const [duplicate, setDuplicate] = useState<{ file: File; title: string } | null>(null);
  const busy = items.some((item) => ["waiting", "uploading", "parsing"].includes(item.phase));
  const allDone = items.length > 0 && !busy;
  const displaySummary = summary || (allDone ? buildResult(items) : null);

  function setBatch(next: UploadItem[]) {
    itemsRef.current = next;
    setItems(next);
  }

  function updateItem(id: string, patch: Partial<UploadItem>) {
    setBatch(itemsRef.current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  async function retryItem(item: UploadItem) {
    if (!item.paper?.id) {
      inputRef.current?.click();
      return;
    }
    updateItem(item.id, { phase: "parsing", progress: 100, error: undefined });
    try {
      await api("/papers/" + item.paper.id + "/reprocess", { method: "POST" });
      const paper = await waitForReady(item.paper.id, (tick) => updateItem(item.id, { paper: tick }));
      if (paper.status === "failed") {
        updateItem(item.id, { phase: "error", error: safeReason(paper.error, "解析失败") });
      } else {
        updateItem(item.id, { phase: "done", paper, error: undefined });
        notifyUsageChanged();
        onBatchUploaded?.([paper]);
        toast("论文已重新解析", "success", paper.title.slice(0, 40));
      }
    } catch (error) {
      updateItem(item.id, { phase: "error", error: safeReason((error as Error).message, "重新解析失败") });
      toast("重新解析失败", "error");
    }
    const result = buildResult(itemsRef.current);
    setSummary(result);
    persistResult(result);
  }

  async function start(files: File[], allowDuplicate = false) {
    if (busy) return;
    const batch: UploadItem[] = files.map((file, index) => {
      let phase: Phase = "waiting";
      let error: string | undefined;
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        phase = "skipped";
        error = "不是 PDF 文件";
      } else if (file.size > 50 * 1024 * 1024) {
        phase = "skipped";
        error = "文件超过 50MB 限制";
      }
      return {
        id: Date.now().toString(36) + "-" + index + "-" + Math.random().toString(36).slice(2, 6),
        file,
        phase,
        progress: 0,
        error,
      };
    });
    setBatch(batch);
    setSummary(null);
    setDuplicate(null);
    const work = batch.filter((item) => item.phase === "waiting");
    const completed: Paper[] = [];
    let duplicateItem: { file: File; title: string } | null = null;

    await mapLimit(work, 2, async (item) => {
      updateItem(item.id, { phase: "uploading", progress: 0, error: undefined });
      try {
        const result = await uploadWithProgress(
          item.file,
          { collectionId, allowDuplicate },
          (percent) => updateItem(item.id, { progress: percent }),
        );
        updateItem(item.id, { phase: "parsing", progress: 100, paper: result.paper });
        const paper = await waitForReady(result.paper.id, (tick) => updateItem(item.id, { paper: tick }));
        if (paper.status === "failed") {
          updateItem(item.id, { phase: "error", error: safeReason(paper.error, "PDF 解析失败") });
          return;
        }
        updateItem(item.id, { phase: "done", paper });
        completed.push(paper);
      } catch (error) {
        const apiError = error as ApiError;
        if (apiError.status === 409) {
          const title = (apiError.detail as { title?: string })?.title || item.file.name;
          if (batch.length === 1) duplicateItem = { file: item.file, title };
          updateItem(item.id, {
            phase: "duplicate",
            error: apiError.status === 409 ? "资料库中已存在，已跳过" : "上传失败",
          });
          return;
        }
        updateItem(item.id, { phase: "error", error: safeReason(apiError.message, "上传失败") });
      }
    });

    const result = buildResult(itemsRef.current);
    setSummary(result);
    persistResult(result);
    if (result.success > 0) {
      notifyUsageChanged();
      onBatchUploaded?.(completed);
      // Keep the result panel open when anything was skipped or failed.
      if (result.failed === 0 && result.skipped === 0) onUploaded?.(completed[completed.length - 1]);
    }
    const level = result.failed > 0 ? "error" : result.skipped > 0 ? "info" : "success";
    const detail = result.failed > 0
      ? result.items.find((row) => row.status === "failed")?.reason
      : result.skipped > 0
        ? result.items.find((row) => row.status === "skipped")?.reason
        : undefined;
    toast(
      "本批次上传完成：成功 " + result.success + "，失败 " + result.failed + "，跳过 " + result.skipped,
      level,
      detail,
    );
    if (duplicateItem) setDuplicate(duplicateItem);
    if (autoNavigate && result.success === 1 && result.failed === 0 && result.skipped === 0) {
      const paper = completed[0];
      if (paper) navigate("/app/papers/" + paper.id);
    }
  }

  function chooseFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    void start(Array.from(fileList));
  }

  return (
    <div className="uploader-wrap">
      <div
        className={"uploader " + (compact ? "uploader-compact " : "") + (dragging ? "uploader-drag " : "") + (items.length ? "uploader-batch-mode" : "")}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!busy) void start(Array.from(event.dataTransfer.files || []));
        }}
        onClick={() => {
          if (!items.length) inputRef.current?.click();
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !items.length) inputRef.current?.click();
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(event) => {
            chooseFiles(event.target.files);
            event.target.value = "";
          }}
        />
        {items.length === 0 && (
          <>
            <span className="upload-icon">
              <CloudUpload size={compact ? 20 : 24} />
            </span>
            <div>
              <strong>{compact ? "上传 PDF 论文" : "拖入 PDF，或点击选择文件"}</strong>
              <p>支持一次选择多份 50MB 以内的学术论文，系统会按队列依次解析</p>
            </div>
          </>
        )}
        {items.length > 0 && (
          <div className="upload-batch">
            <div className="upload-batch-head">
              <span>
                {busy ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
                {busy ? "正在处理 " + items.length + " 份论文" : "本批次 " + items.length + " 份论文"}
              </span>
              <span>{displaySummary ? "成功 " + displaySummary.success + " · 失败 " + displaySummary.failed + " · 跳过 " + displaySummary.skipped : "后端队列串行解析"}</span>
            </div>
            {items.map((item) => (
              <div key={item.id} className={"upload-item upload-item-" + item.phase}>
                <div className="upload-item-head">
                  <span className="upload-item-name">
                    <FileText size={13} />
                    {item.file.name}
                  </span>
                  <strong>
                    {item.phase === "done"
                      ? "成功"
                      : item.phase === "error"
                        ? "失败"
                        : item.phase === "duplicate" || item.phase === "skipped"
                          ? "跳过"
                          : item.phase === "parsing"
                            ? "解析中"
                            : item.phase === "uploading"
                              ? item.progress + "%"
                              : "等待"}
                  </strong>
                </div>
                <div className="upload-item-track">
                  <span style={{ width: (item.phase === "done" ? 100 : item.progress) + "%" }} />
                </div>
                <div className="upload-item-meta">
                  <span>{formatBytes(item.file.size)}</span>
                  {item.paper?.page_count ? <span>{item.paper.page_count} 页</span> : null}
                  {item.error ? <span className="upload-item-error">{item.error}</span> : null}
                  {item.phase === "error" && (
                    <button
                      className="upload-item-retry"
                      onClick={(event) => {
                        event.stopPropagation();
                        void retryItem(item);
                      }}
                    >
                      <RotateCcw size={11} /> {item.paper ? "重新解析" : "重新选择"}
                    </button>
                  )}
                </div>
              </div>
            ))}
            {allDone && (
              <div className="upload-actions">
                {displaySummary && displaySummary.success > 0 && (
                  <Button size="sm" variant="primary" onClick={(event) => { event.stopPropagation(); navigate("/app/papers"); }}>
                    查看资料库
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); setBatch([]); setSummary(null); }}>
                  继续上传
                </Button>
              </div>
            )}
          </div>
        )}
        {items.length === 0 && dragging && <div className="upload-drop-hint"><FileUp size={16} /> 松开以添加多份 PDF</div>}
      </div>

      <Modal
        open={Boolean(duplicate)}
        onClose={() => setDuplicate(null)}
        title="资料库中已存在这篇论文"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDuplicate(null)}>取消</Button>
            <Button
              variant="primary"
              onClick={() => {
                const pending = duplicate;
                setDuplicate(null);
                if (pending) void start([pending.file], true);
              }}
            >
              仍然上传
            </Button>
          </>
        }
      >
        <p className="muted">
          《{duplicate?.title}》已存在。重复上传会创建独立副本并重新解析。
        </p>
        <Button variant="soft" size="sm" onClick={() => { setDuplicate(null); navigate("/app/papers"); }}>
          去论文库查看
        </Button>
      </Modal>
    </div>
  );
}

export function UploadResultNotice() {
  const { toast } = useApp();
  const [result, setResult] = useState<UploadBatchResult | null>(() => readResult());
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const refresh = () => {
      setResult(readResult());
      setHidden(false);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === UPLOAD_RESULT_KEY) refresh();
    };
    window.addEventListener(UPLOAD_RESULT_EVENT, refresh);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(UPLOAD_RESULT_EVENT, refresh);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  if (!result || result.failed + result.skipped === 0 || hidden) return null;

  async function retry(row: UploadResultItem) {
    if (!row.paperId) {
      toast("该文件没有生成论文记录，请在论文阅读页重新选择文件", "info");
      return;
    }
    try {
      await api("/papers/" + row.paperId + "/reprocess", { method: "POST" });
      toast("已重新排队解析", "info", row.filename);
    } catch {
      toast("重新解析失败", "error", row.filename);
    }
  }

  return (
    <>
      <div className="upload-result-banner">
        <AlertTriangle size={14} />
        <span>
          上次上传：成功 {result.success} · 失败 {result.failed} · 跳过 {result.skipped}
        </span>
        <button onClick={() => setOpen(true)}>查看结果</button>
        <button className="upload-result-close" onClick={() => setHidden(true)} aria-label="关闭上传结果">×</button>
      </div>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="上次上传结果"
        size="md"
        footer={<Button variant="ghost" onClick={() => setOpen(false)}>关闭</Button>}
      >
        <div className="upload-result-table">
          {result.items.map((row) => (
            <div key={row.filename + row.status} className="upload-result-row">
              <span className="upload-result-name">{row.filename}</span>
              <strong className={"upload-result-" + row.status}>{row.status === "success" ? "成功" : row.status === "failed" ? "失败" : "跳过"}</strong>
              <span className="upload-result-reason">{row.reason || (row.status === "success" ? "解析完成" : "")}</span>
              {row.status === "failed" && row.paperId && (
                <button className="upload-item-retry" onClick={() => void retry(row)}>
                  <RotateCcw size={11} /> 重新解析
                </button>
              )}
            </div>
          ))}
        </div>
      </Modal>
    </>
  );
}