import { useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CloudUpload, FileUp, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../store/AppContext";
import { ApiError, authHeaders, getToken } from "../lib/api";
import { formatBytes } from "../lib/utils";
import { Button, Modal } from "./ui";
import type { Paper } from "../lib/types";

type Phase = "idle" | "uploading" | "parsing" | "done" | "error";

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
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const response = await fetch("/api/papers/" + paperId, { headers: authHeaders() });
    if (response.ok) {
      const paper = (await response.json()) as Paper;
      onTick(paper);
      if (paper.status === "ready" || paper.status === "failed") return paper;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
  throw new Error("解析超时，请稍后在论文库中查看处理状态");
}

export function Uploader({
  collectionId,
  onUploaded,
  compact = false,
  autoNavigate = false,
}: {
  collectionId?: string;
  onUploaded?: (paper: Paper) => void;
  compact?: boolean;
  autoNavigate?: boolean;
}) {
  const { toast } = useApp();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({ phase: "idle", progress: 0 });
  const [dragging, setDragging] = useState(false);
  const [duplicate, setDuplicate] = useState<{ file: File; title: string } | null>(null);

  async function start(file: File, allowDuplicate = false) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast("仅支持 PDF 文件", "error");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast("文件超过 50MB 限制", "error");
      return;
    }
    setState({ phase: "uploading", progress: 0, filename: file.name });
    try {
      const result = await uploadWithProgress(
        file,
        { collectionId, allowDuplicate },
        (percent) => setState((current) => ({ ...current, progress: percent })),
      );
      setState({ phase: "parsing", progress: 100, filename: file.name, paper: result.paper });
      const paper = await waitForReady(result.paper.id, (tick) =>
        setState((current) => ({ ...current, paper: tick })),
      );
      if (paper.status === "failed") {
        setState({ phase: "error", progress: 100, filename: file.name, paper, error: paper.error || "解析失败" });
        toast("论文解析失败", "error", paper.error || undefined);
        return;
      }
      setState({ phase: "done", progress: 100, filename: file.name, paper });
      onUploaded?.(paper);
      toast("论文已解析完成", "success", paper.title.slice(0, 40));
      if (autoNavigate) navigate("/app/papers/" + paper.id);
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 409) {
        setDuplicate({ file, title: (apiError.detail as { title?: string })?.title || file.name });
        setState({ phase: "idle", progress: 0 });
        return;
      }
      setState({ phase: "error", progress: 0, filename: file.name, error: apiError.message || "上传失败" });
      toast(apiError.message || "上传失败", "error");
    }
  }

  return (
    <div className="uploader-wrap">
      <div
        className={"uploader " + (compact ? "uploader-compact " : "") + (dragging ? "uploader-drag" : "")}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void start(file);
        }}
        onClick={() => state.phase === "idle" && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => event.key === "Enter" && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void start(file);
            event.target.value = "";
          }}
        />
        {state.phase === "idle" && (
          <>
            <span className="upload-icon">
              <CloudUpload size={compact ? 20 : 24} />
            </span>
            <div>
              <strong>{compact ? "上传 PDF 论文" : "拖入 PDF，或点击选择文件"}</strong>
              <p>支持 50MB 以内的学术论文，解析后自动建立可检索的知识切片</p>
            </div>
          </>
        )}
        {state.phase === "uploading" && (
          <div className="upload-progress">
            <div className="upload-file">
              <FileUp size={17} />
              <span>{state.filename}</span>
              <strong>{state.progress}%</strong>
            </div>
            <div className="progress">
              <span className="progress-fill" style={{ width: state.progress + "%" }} />
            </div>
          </div>
        )}
        {state.phase === "parsing" && (
          <div className="upload-progress">
            <div className="upload-file">
              <Loader2 size={17} className="spin" />
              <span>正在解析 {state.filename}</span>
              <strong>{formatBytes(state.paper?.size_bytes)}</strong>
            </div>
            <p className="muted small">提取章节、段落、图表与页码坐标…</p>
          </div>
        )}
        {state.phase === "done" && state.paper && (
          <div className="upload-progress">
            <div className="upload-file">
              <CheckCircle2 size={17} className="text-success" />
              <span>{state.paper.title}</span>
            </div>
            <p className="muted small">
              {state.paper.page_count} 页 · {state.paper.chunks_count ?? 0} 个切片 ·{" "}
              {state.paper.sections?.length ?? 0} 个章节
            </p>
            <div className="upload-actions">
              <Button size="sm" variant="primary" onClick={(event) => { event.stopPropagation(); navigate("/app/papers/" + state.paper!.id); }}>
                开始阅读
              </Button>
              <Button size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); setState({ phase: "idle", progress: 0 }); }}>
                继续上传
              </Button>
            </div>
          </div>
        )}
        {state.phase === "error" && (
          <div className="upload-progress">
            <div className="upload-file">
              <AlertTriangle size={17} className="text-danger" />
              <span>{state.error}</span>
            </div>
            <div className="upload-actions">
              <Button size="sm" onClick={(event) => { event.stopPropagation(); setState({ phase: "idle", progress: 0 }); }}>
                重试
              </Button>
            </div>
          </div>
        )}
      </div>

      <Modal
        open={Boolean(duplicate)}
        onClose={() => setDuplicate(null)}
        title="资料库中已存在这篇论文"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDuplicate(null)}>
              取消
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                const pending = duplicate;
                setDuplicate(null);
                if (pending) void start(pending.file, true);
              }}
            >
              仍然上传
            </Button>
          </>
        }
      >
        <p className="muted">
          《{duplicate?.title}》已存在。重复上传会创建独立副本并重新解析，通常没有必要。你也可以直接打开已有论文继续阅读。
        </p>
        <Button
          variant="soft"
          size="sm"
          onClick={() => {
            setDuplicate(null);
            navigate("/app/papers");
          }}
        >
          去论文库查看
        </Button>
      </Modal>
    </div>
  );
}
