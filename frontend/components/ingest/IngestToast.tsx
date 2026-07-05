"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

export interface IngestToastItem {
  id: string;
  variant: "success" | "error" | "created";
  title: string;
  description?: string;
  /** Subtitle (e.g. queue-position hint). */
  hint?: string;
  documentId?: string;
}

interface IngestToastProps {
  toasts: IngestToastItem[];
  onDismiss: (id: string) => void;
}

const SUCCESS_TIMEOUT = 4000;
const ERROR_TIMEOUT = 6000;

function ToastCard({
  toast,
  onDismiss,
}: {
  toast: IngestToastItem;
  onDismiss: (id: string) => void;
}) {
  const t = useTranslations("ingest.toast");

  useEffect(() => {
    const timeout = setTimeout(
      () => onDismiss(toast.id),
      toast.variant === "error" ? ERROR_TIMEOUT : SUCCESS_TIMEOUT,
    );
    return () => clearTimeout(timeout);
  }, [toast.id, toast.variant, onDismiss]);

  const isError = toast.variant === "error";

  return (
    <output className="pointer-events-auto flex w-96 items-start gap-3 rounded-xl border border-border bg-surface p-3.5 shadow-lg">
      <div
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
          isError ? "bg-danger-soft" : "bg-success-soft"
        }`}
      >
        {isError ? (
          <AlertCircle className="h-4 w-4 text-danger" aria-hidden />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{toast.title}</p>
        {toast.hint && (
          <p className="mt-1 text-xs leading-relaxed text-foreground-secondary">{toast.hint}</p>
        )}
        {toast.description && (
          <p
            className="mt-0.5 truncate text-xs text-foreground-secondary"
            title={toast.description}
          >
            {toast.description}
          </p>
        )}
        {toast.documentId && (
          <p
            className="mt-0.5 truncate font-mono text-[11px] text-foreground-tertiary"
            title={toast.documentId}
          >
            {t("documentId")}: {toast.documentId}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label={t("dismiss")}
        className="shrink-0 rounded p-0.5 text-foreground-tertiary hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </output>
  );
}

/** Fixed-position toast stack (top-right). Self-contained — no provider needed. */
export function IngestToast({ toasts, onDismiss }: IngestToastProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
