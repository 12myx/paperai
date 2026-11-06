import { useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CloudUpload, FileText, FileUp, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../store/AppContext";
import { ApiError, authHeaders, getToken } from "../lib/api";
import { formatBytes } from "../lib/utils";
import { Button, Modal } from "./ui";
import type { Paper } from "../lib/types";

type Phase = "waiting" | "uploading" | "parsing" | "done" | "error" | "duplicate";

interface UploadItem {
  id: string;
  file: File;
  phase: Phase;
  progress: number;
  paper?: Paper;
  error?: string;
}

export interface UploadState {
  phase: Phase;
  progress: number;
  filename?: string;
  paper?: Paper;
  error?: string;
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
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [duplicate, setDuplicate] = useState<{ file: File; title: string } | null>(null);
  const busy = items.some((item) => ["waiting", "uploading", "parsing"].includes(item.phase));
  const allDone = items.length > 0 && !busy;

  function updateItem(id: string, patch: Partial<UploadItem>) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  async function start(files: File[], allowDuplicate = false) {
    if (busy) return;
    const valid = files.filter((file) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        toast("已跳过非 PDF 文件：" + file.name, "error");
        return false;
      }
      if (file.size > 50 * 1024 * 1024) {
        toast("已跳过超过 50MB 的文件：" + file.name, "error");
        return false;
      }
      return true;
    });
    if (!valid.length) return;
    const batch: UploadItem[] = valid.map((file, index) => ({
      id: Date.now().toString(36) + "-" + index + "-" + Math.random().toString(36).slice(2, 6),
      file,
      phase: "waiting",
      progress: 0,
    }));
    setItems(batch);
    setDuplicate(null);
    const completed: Paper[] = [];
    let duplicateItem: { file: File; title: string } | null = null;
    let failedCount = 0;
    const single = valid.length === 1;

    await mapLimit(batch, 2, async (item) => {
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
          const error = paper.error || "解析失败";
          updateItem(item.id, { phase: "error", error });
          return;
        }
        updateItem(item.id, { phase: "done", paper });
        completed.push(paper);
      } catch (error) {
        const apiError = error as ApiError;
        if (apiError.status === 409) {
          const title = (apiError.detail as { title?: string })?.title || item.file.name;
          if (single) duplicateItem = { file: item.file, title };
          updateItem(item.id, {
            phase: "duplicate",
            error: single ? "资料库中已存在" : "资料库中已存在，已跳过",
          });
          failedCount += 1;
          return;
        }
        const message = apiError.message || "上传失败";
        failedCount += 1;
        updateItem(item.id, { phase: "error", error: message });
      }
    });

    if (completed.length) {
      if (onBatchUploaded) onBatchUploaded(completed);
      else onUploaded?.(completed[completed.length - 1]);
      toast(
        completed.length + " 篇论文已解析完成" + (duplicateItem ? "；有重复文件待确认" : ""),
        "success",
        completed.map((paper) => paper.title).slice(0, 2).join("、"),
      );
      if (autoNavigate) {
        if (completed.length === 1) navigate("/app/papers/" + completed[0].id);
        else navigate("/app/papers");
      }
    } else if (duplicateItem) {
      // Modal below offers "仍然上传"; the batch itself made no changes.
    } else {
      if (failedCount) toast(failedCount + " 个文件上传、解析失败或重复", "error");
    }
    if (duplicateItem) setDuplicate(duplicateItem);
  }

  function chooseFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    void start(Array.from(fileList));
  }

  return (
    <div className="uploader-wrap">
      <div
        className={"uploader " + (compact ? "uploader-compact " : "") + (dragging ? "uploader-drag" : "") + (items.length ? " uploader-batch-mode" : "")}
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
              <span>后端队列串行解析</span>
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
                      ? "完成"
                      : item.phase === "error"
                        ? "失败"
                        : item.phase === "duplicate"
                          ? "重复"
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
                </div>
              </div>
            ))}
            {allDone && (
              <div className="upload-actions">
                {items.some((item) => item.paper) && (
                  <Button size="sm" variant="primary" onClick={(event) => { event.stopPropagation(); navigate("/app/papers"); }}>
                    查看资料库
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); setItems([]); }}>
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