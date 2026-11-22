import { forwardRef, useEffect, useRef } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { cn } from "../lib/utils";
import { useApp } from "../store/AppContext";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "soft";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      className={cn("btn", "btn-" + variant, "btn-" + size, className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 size={15} className="spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button className={cn("icon-btn", className)} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn("input", className)} {...rest} />;
  },
);

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("textarea", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("select", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label?: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("field", className)}>
      {label && <span className="field-label">{label}</span>}
      {children}
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </label>
  );
}

export function Card({
  className,
  children,
  as: Tag = "div",
  ...rest
}: {
  className?: string;
  children: ReactNode;
  as?: "div" | "section" | "article";
} & Record<string, unknown>) {
  return (
    <Tag className={cn("card", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "warn" | "danger" | "info";
  className?: string;
}) {
  return <span className={cn("badge", "badge-" + tone, className)}>{children}</span>;
}

export function Chip({
  active,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button className={cn("chip", active && "chip-active", className)} {...rest}>
      {children}
    </button>
  );
}

export function Avatar({
  name,
  color = "#2F6F62",
  size = 36,
}: {
  name: string;
  color?: string;
  size?: number;
}) {
  const text = name?.trim() ? name.trim().slice(0, 2).toUpperCase() : "PL";
  return (
    <span
      className="avatar"
      style={{ width: size, height: size, background: color, fontSize: Math.max(11, size * 0.34) }}
      aria-hidden="true"
    >
      {text}
    </span>
  );
}

export function Spinner({ size = 18 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("empty-state", className)}>
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="modal-root" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={cn("modal", "modal-" + size)} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panel}>
        {(title || subtitle) && (
          <header className="modal-head">
            <div>
              {title && <h2>{title}</h2>}
              {subtitle && <p>{subtitle}</p>}
            </div>
            <IconButton label="关闭" onClick={onClose}>
              <X size={18} />
            </IconButton>
          </header>
        )}
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  danger = false,
  onConfirm,
  onClose,
  loading = false,
}: {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  loading?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {description && <p className="muted">{description}</p>}
    </Modal>
  );
}

export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: { id: string; label: string; count?: number }[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("tabs", className)} role="tablist">
      {items.map((item) => (
        <button
          key={item.id}
          role="tab"
          aria-selected={value === item.id}
          className={cn("tab", value === item.id && "tab-active")}
          onClick={() => onChange(item.id)}
        >
          {item.label}
          {typeof item.count === "number" && <span className="tab-count">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function ProgressBar({ value, tone = "accent" }: { value: number; tone?: "accent" | "warn" }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <span className={cn("progress-fill", tone === "warn" && "progress-warn")} style={{ width: Math.max(0, Math.min(100, value)) + "%" }} />
    </div>
  );
}

export function Toasts() {
  const { toasts, dismissToast } = useApp();
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={cn("toast", "toast-" + toast.kind)}>
          {toast.kind === "success" ? <CheckCircle2 size={17} /> : toast.kind === "error" ? <AlertTriangle size={17} /> : <Info size={17} />}
          <div className="toast-body">
            <strong>{toast.message}</strong>
            {toast.detail && <span>{toast.detail}</span>}
          </div>
          <button className="toast-close" onClick={() => dismissToast(toast.id)} aria-label="关闭提示">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function Divider({ label }: { label?: string }) {
  return (
    <div className="divider">
      <span>{label}</span>
    </div>
  );
}