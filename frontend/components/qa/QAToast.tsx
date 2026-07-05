"use client";

import { AlertCircle, X } from "lucide-react";
import { useEffect } from "react";

export interface QAToastItem {
  id: string;
  variant: "error" | "success";
  title: string;
  description?: string;
}

interface QAToastProps {
  toasts: QAToastItem[];
  onDismiss: (id: string) => void;
}

const ERROR_TIMEOUT = 6000;
const SUCCESS_TIMEOUT = 4000;

function ToastCard({ toast, onDismiss }: { toast: QAToastItem; onDismiss: (id: string) => void }) {
  useEffect(() => {
    const timeout = setTimeout(
      () => onDismiss(toast.id),
      toast.variant === "error" ? ERROR_TIMEOUT : SUCCESS_TIMEOUT,
    );
    return () => clearTimeout(timeout);
  }, [toast.id, toast.variant, onDismiss]);

  const isError = toast.variant === "error";

  return (
    <output className="pointer-events-auto flex w-80 items-start gap-3 rounded-xl border border-border bg-surface p-3 shadow-[0_8px_24px_0_rgba(0,0,0,0.10)]">
      <div
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
          isError ? "bg-danger-soft" : "bg-success-soft"
        }`}
      >
        <AlertCircle
          className={`h-4 w-4 ${isError ? "text-danger" : "text-success"}`}
          aria-hidden
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 break-words text-xs text-muted" title={toast.description}>
            {toast.description}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="close"
        className="shrink-0 rounded p-0.5 text-muted hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </output>
  );
}

/** Fixed-position toast stack (top-right) for Q&A error/success notices. */
export function QAToast({ toasts, onDismiss }: QAToastProps) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed right-4 top-16 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
