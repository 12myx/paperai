export const USAGE_CHANGED_EVENT = "paperlens:usage-changed";

export function notifyUsageChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(USAGE_CHANGED_EVENT));
  }
}
export const UPLOAD_RESULT_EVENT = "paperlens:upload-result";
