"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export interface KBToastItem {
  id: string;
  variant: "success" | "error";
  title: string;
  description?: string;
}

interface KBToastContextValue {
  pushToast: (toast: Omit<KBToastItem, "id">) => void;
  dismissToast: (id: string) => void;
}

const KBToastContext = createContext<KBToastContextValue | null>(null);

const SUCCESS_TIMEOUT = 4000;
const ERROR_TIMEOUT = 6000;

function ToastCard({ toast, onDismiss }: { toast: KBToastItem; onDismiss: (id: string) => void }) {
  const isError = toast.variant === "error";

  // Auto-dismiss timer.
  useEffect(() => {
    const timeout = setTimeout(
      () => onDismiss(toast.id),
      isError ? ERROR_TIMEOUT : SUCCESS_TIMEOUT,
    );
    return () => clearTimeout(timeout);
  }, [toast.id, isError, onDismiss]);

  return (
    <output className="pointer-events-auto flex w-96 items-start gap-3 rounded-xl border border-border bg-surface p-3.5 shadow-[0_8px_24px_0_rgba(0,0,0,0.10)]">
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
        {toast.description && (
          <p
            className="mt-0.5 break-words text-xs text-foreground-secondary"
            title={toast.description}
          >
            {toast.description}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="close"
        className="shrink-0 rounded p-0.5 text-foreground-tertiary hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </output>
  );
}

function ToastStack({
  toasts,
  onDismiss,
}: { toasts: KBToastItem[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed right-4 top-16 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export function KBToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<KBToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback((toast: Omit<KBToastItem, "id">) => {
    const id = `kb-toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((prev) => [...prev, { ...toast, id }]);
  }, []);

  const value = useMemo(() => ({ pushToast, dismissToast }), [pushToast, dismissToast]);

  return (
    <KBToastContext.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </KBToastContext.Provider>
  );
}

export function useKBToast(): KBToastContextValue {
  const ctx = useContext(KBToastContext);
  if (!ctx) {
    throw new Error("useKBToast must be used within a KBToastProvider");
  }
  return ctx;
}
