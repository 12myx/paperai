export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}

export function relativeTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value).getTime();
  if (Number.isNaN(date)) return "";
  const diff = Date.now() - date;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return minutes + " 分钟前";
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours + " 小时前";
  const days = Math.round(hours / 24);
  if (days < 30) return days + " 天前";
  return formatDate(value);
}

export function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1) + " " + units[index];
}

export function truncate(text: string, length: number): string {
  if (!text) return "";
  return text.length > length ? text.slice(0, length - 1) + "…" : text;
}

export function initials(name?: string | null): string {
  if (!name) return "PL";
  const trimmed = name.trim();
  if (!trimmed) return "PL";
  if (/^[\u4e00-\u9fff]/.test(trimmed)) return trimmed.slice(0, 2);
  const parts = trimmed.split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

export function debounce<T extends (...args: never[]) => void>(fn: T, delay = 300) {
  let timer: number | undefined;
  return (...args: Parameters<T>) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

export const MODES = [
  { id: "quick", label: "快速问答", hint: "先给结论，再给证据" },
  { id: "deep_read", label: "深度阅读", hint: "逐段分析方法与实验" },
  { id: "multi_paper", label: "多论文研究", hint: "横向对比多篇文献" },
  { id: "critical", label: "批判性分析", hint: "检验方法、实验与结论" },
  { id: "explore", label: "研究探索", hint: "寻找分歧与研究缺口" },
] as const;

export const SUMMARY_MODES = [
  { id: "one_line", label: "一句话", hint: "核心贡献" },
  { id: "abstract", label: "摘要", hint: "150-250 字" },
  { id: "section", label: "章节", hint: "逐章梳理" },
  { id: "full", label: "全文", hint: "完整综述" },
  { id: "plain", label: "通俗版", hint: "给非本领域读者" },
  { id: "academic", label: "学术版", hint: "保留术语指标" },
  { id: "method", label: "方法", hint: "技术路线" },
  { id: "experiment", label: "实验", hint: "数据与基线" },
  { id: "innovation", label: "创新点", hint: "区分声称与推断" },
  { id: "limitation", label: "局限", hint: "假设与覆盖" },
  { id: "future", label: "未来方向", hint: "后续研究" },
] as const;

export const ANNOTATION_COLORS = [
  { id: "yellow", label: "重要观点", color: "#E8C468" },
  { id: "blue", label: "研究方法", color: "#7FA9CF" },
  { id: "green", label: "创新点", color: "#84BE9C" },
  { id: "red", label: "存在问题", color: "#D98C7F" },
  { id: "purple", label: "待研究", color: "#B49ACB" },
] as const;

export const KNOWLEDGE_KINDS = [
  { id: "note", label: "笔记" },
  { id: "summary", label: "总结" },
  { id: "insight", label: "观点" },
  { id: "method", label: "方法论" },
  { id: "result", label: "实验结论" },
  { id: "question", label: "研究问题" },
  { id: "quote", label: "原文片段" },
] as const;

export const EVIDENCE_TYPES = [
  { id: "direct", label: "原文直接证据", short: "原文", hint: "论文原文中可直接核对的句子" },
  { id: "shared", label: "多篇论文共同支持", short: "共识", hint: "多篇论文指向同一发现" },
  { id: "inferred", label: "AI 基于证据的推导", short: "推导", hint: "由引用证据归纳，但不是原文原句" },
  { id: "hypothesis", label: "AI 研究假设", short: "假设", hint: "尚未被资料库验证的研究想法" },
  { id: "insufficient", label: "证据不足", short: "不足", hint: "当前资料库无法支撑该结论" },
  { id: "external", label: "需要外部验证", short: "外部", hint: "需要外部文献或实验数据" },
] as const;

export function evidenceLabel(type: string): string {
  return EVIDENCE_TYPES.find((item) => item.id === type)?.label || type;
}

export function evidenceShort(type: string): string {
  return EVIDENCE_TYPES.find((item) => item.id === type)?.short || type;
}

export function plainText(text: string | null | undefined, limit = 260): string {
  if (!text) return "";
  const cleaned = text
    .replace(/^\s*>.*$/gm, "")
    .replace(/^\s*#{1,6}\s.*$/gm, "")
    .replace(/[*_`]/g, "")
    .replace(/\[C\d+\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > limit ? cleaned.slice(0, limit - 1) + "…" : cleaned;
}
