import type { StreamEvent } from "./types";

export const TOKEN_KEY = "paperlens.token";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
    if (detail && typeof detail === "object" && "code" in (detail as Record<string, unknown>)) {
      this.code = String((detail as Record<string, unknown>).code);
    }
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return { ...(token ? { Authorization: "Bearer " + token } : {}), ...(extra || {}) };
}

function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
  }
  return fallback;
}

export type ApiOptions = Omit<RequestInit, "body"> & { body?: unknown };

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...((options.headers as Record<string, string>) || {}),
  };
  let body = options.body as BodyInit | null | undefined;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const response = await fetch("/api" + path, { ...options, headers, body });
  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent("paperlens:unauthorized"));
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      const payload = await response.json();
      detail = payload.detail ?? payload;
    } catch {
      detail = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, messageFromDetail(detail, "请求失败（" + response.status + "）"), detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function uploadPaper(file: File, options: { tags?: string; collectionId?: string; allowDuplicate?: boolean } = {}) {
  const form = new FormData();
  form.append("file", file);
  if (options.tags) form.append("tags", options.tags);
  if (options.collectionId) form.append("collection_id", options.collectionId);
  if (options.allowDuplicate) form.append("allow_duplicate", "true");
  return api<{ paper: import("./types").Paper; duplicate: boolean }>("/papers", { method: "POST", body: form });
}

export async function uploadPdf(
  file: File,
  options: { tags?: string; collectionId?: string; allowDuplicate?: boolean } = {},
): Promise<import("./types").Paper> {
  const form = new FormData();
  form.append("file", file);
  if (options.tags) form.append("tags", options.tags);
  if (options.collectionId) form.append("collection_id", options.collectionId);
  if (options.allowDuplicate) form.append("allow_duplicate", "true");
  const created = await api<{ paper: import("./types").Paper }>("/papers", { method: "POST", body: form });
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const paper = await api<import("./types").Paper>("/papers/" + created.paper.id);
    if (paper.status !== "processing") return paper;
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  return created.paper;
}

async function streamUrl(
  url: string,
  payload: Record<string, unknown>,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onError: (error: Error) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
      signal: handlers.signal,
    });
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = (await response.json()).detail;
      } catch {
        detail = null;
      }
      throw new ApiError(response.status, messageFromDetail(detail, "无法开始生成"), detail);
    }
    if (!response.body) throw new Error("浏览器不支持流式响应");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        try {
          handlers.onEvent(JSON.parse(line.slice(6)) as StreamEvent);
        } catch {
          // ignore malformed frames
        }
      }
    }
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    handlers.onError(error as Error);
  }
}

export async function streamChat(
  payload: Record<string, unknown>,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onError: (error: Error) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  return streamUrl("/api/chat/stream", payload, handlers);
}

export async function streamTask(
  taskId: string,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onError: (error: Error) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  return streamUrl("/api/agent/tasks/" + taskId + "/execute", {}, handlers);
}

export function apiPath(path: string): string {
  return path.startsWith("/api/") ? path : "/api" + path;
}

export async function blobUrl(path: string): Promise<string> {
  const response = await fetch(apiPath(path), { headers: authHeaders() });
  if (!response.ok) throw new ApiError(response.status, "文件加载失败");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export async function downloadFile(path: string, filename?: string): Promise<void> {
  const response = await fetch(apiPath(path), { headers: authHeaders() });
  if (!response.ok) throw new ApiError(response.status, "下载失败");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "paperlens-export";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}