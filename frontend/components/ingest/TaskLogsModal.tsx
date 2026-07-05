"use client";

import {
  type TaskPhase,
  documentName,
  normalizeStatus,
  parseTask,
} from "@/components/ingest/status";
import { cn } from "@/components/ui";
import { streamTaskProgress } from "@/lib/api/sse";
import { errorMessage, useTaskLogs } from "@/lib/hooks/useIngest";
import type { Task, TaskLog } from "@/lib/types";
import { Button, Modal, Spinner, useOverlayState } from "@heroui/react";
import { AlertTriangle, Check, Copy, FileText, RotateCcw, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

interface ParsedLine {
  ts: string;
  level: string;
  source: string;
  message: string;
  /** Normalized level used for color mapping. */
  kind: "error" | "success" | "warn" | "debug" | "info";
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function parseLine(log: TaskLog): ParsedLine {
  const ts = str(log.ts) || str(log.time) || str(log.timestamp);
  const level = (str(log.level) || str(log.severity)).toUpperCase();
  const source = str(log.source) || str(log.component) || str(log.logger);
  const message = str(log.message) || str(log.msg) || str(log.event) || str(log.text);
  let kind: ParsedLine["kind"] = "info";
  if (level.includes("ERROR") || level.includes("CRIT") || level.includes("FATAL")) kind = "error";
  else if (level.includes("SUCCESS")) kind = "success";
  else if (level.includes("WARN")) kind = "warn";
  else if (level.includes("DEBUG") || level.includes("TRACE")) kind = "debug";
  return { ts, level, source, message: message || JSON.stringify(log), kind };
}

const KIND_CLASS: Record<ParsedLine["kind"], string> = {
  error: "-mx-4 block bg-[#ff383c1f] px-4 py-0.5 font-medium text-[#ff7a7d]",
  success: "-mx-4 block bg-[#17c9641f] px-4 py-0.5 font-medium text-[#5fe08a]",
  warn: "text-[#f5b544]",
  debug: "text-zinc-500",
  info: "text-zinc-400",
};

const STATUS_PILL: Record<TaskPhase, { class: string; key: string }> = {
  failed: { class: "bg-danger-soft text-danger", key: "failed" },
  success: { class: "bg-success-soft text-success", key: "success" },
  running: { class: "bg-accent-soft text-accent", key: "running" },
  pending: { class: "bg-warning-soft text-warning", key: "pending" },
};

function durationSeconds(task: Task): number | null {
  if (!task.created_at || !task.updated_at) return null;
  const start = new Date(task.created_at).getTime();
  const end = new Date(task.updated_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  return Math.round((end - start) / 1000);
}

interface TaskLogsModalProps {
  task: Task;
  onClose: () => void;
  onRetry: (task: Task) => void;
}

/**
 * TaskLogsModal — terminal-style task log panel.
 * mac three-colour dots + LIVE badge + severity-coloured log rows (ERROR red bar /
 * SUCCESS green bar) + exit code footer. Failure state offers "retry", others
 * offer "close".
 */
export function TaskLogsModal({ task, onClose, onRetry }: TaskLogsModalProps) {
  const t = useTranslations("ingest");
  const state = useOverlayState({
    defaultOpen: true,
    onOpenChange: (open) => {
      if (!open) onClose();
    },
  });

  const [snapshot, setSnapshot] = useState<Task>(task);
  const [liveLogs, setLiveLogs] = useState<TaskLog[] | null>(null);
  const [copied, setCopied] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const streamRunning = useRef(normalizeStatus(task.status) === "running");

  const logsQuery = useTaskLogs(task.job_id);
  const rawLogs = (liveLogs ?? logsQuery.data?.logs ?? []) as TaskLog[];
  const lines = useMemo(() => rawLogs.map(parseLine), [rawLogs]);
  const loadingLogs = logsQuery.isLoading;
  const logError = logsQuery.error ? errorMessage(logsQuery.error) : null;

  useEffect(() => {
    if (!streamRunning.current) return;
    let cancelled = false;
    const cancelStream = streamTaskProgress(
      task.job_id,
      (event) => {
        if (event.event !== "progress") return;
        const updated = parseTask(event.data);
        if (!updated) return;
        setSnapshot((prev) => ({ ...prev, ...updated }));
        if (Array.isArray(updated.logs) && updated.logs.length > 0) {
          setLiveLogs(updated.logs as TaskLog[]);
        }
      },
      (err) => {
        if (!cancelled) setLiveLogs([{ level: "ERROR", message: err.message }]);
      },
    );
    return () => {
      cancelled = true;
      cancelStream?.();
    };
  }, [task.job_id]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const phase = normalizeStatus(snapshot.status);
  const isFailed = phase === "failed";
  const isSuccess = phase === "success";
  const exitCode = isFailed ? 1 : isSuccess ? 0 : null;
  const duration = durationSeconds(snapshot);
  const pill = STATUS_PILL[phase];
  const kbName = snapshot.kb_name || "default";
  // Design: only the success state is a finished bash session; others (running / failed / queued) keep tail -f + LIVE.
  const showLive = !isSuccess;
  const shell = isSuccess ? "bash" : "tail -f";

  const footerMeta = [
    exitCode != null ? t("logs.exitCode", { code: exitCode }) : null,
    t("logs.lines", { count: lines.length }),
    isSuccess && duration != null
      ? t("logs.duration", { seconds: duration })
      : t("logs.streamEnded"),
  ]
    .filter(Boolean)
    .join(" · ");

  const copyLogs = () => {
    const text = lines
      .map((l) =>
        [
          l.ts ? `[${l.ts}]` : "",
          l.level ? `[${l.level}]` : "",
          l.source ? `[${l.source}]` : "",
          l.message,
        ]
          .filter(Boolean)
          .join(" "),
      )
      .join("\n");
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <Modal state={state}>
      <Modal.Backdrop className="backdrop-blur-sm">
        <Modal.Container>
          <Modal.Dialog aria-label={t("logs.title")} className="w-[1040px] max-w-[94vw]">
            {/* Header */}
            <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-4">
              <div className="flex min-w-0 flex-col gap-1">
                <h2 className="text-base font-semibold text-foreground">{t("logs.title")}</h2>
                <p className="flex min-w-0 items-center gap-1.5 text-xs text-foreground-secondary">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-foreground-tertiary" aria-hidden />
                  <span className="truncate">
                    {documentName(snapshot)} · kb: {kbName}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
                    pill.class,
                  )}
                >
                  {isSuccess ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
                  ) : (
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{
                        backgroundImage:
                          "repeating-linear-gradient(45deg, currentColor 0 1.5px, transparent 1.5px 3px)",
                      }}
                      aria-hidden
                    />
                  )}
                  {t(`logs.${pill.key}`)}
                </span>
                <button
                  type="button"
                  onClick={state.close}
                  aria-label={t("logs.close")}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-(--surface-muted) text-foreground-secondary transition-colors hover:text-foreground"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </div>

            {/* Terminal */}
            <div className="px-5">
              <div className="overflow-hidden rounded-xl bg-[#0d0d0d]">
                <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
                  <span className="flex items-center gap-1.5" aria-hidden>
                    <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                    <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
                    <span className="h-3 w-3 rounded-full bg-[#28c840]" />
                  </span>
                  {showLive ? (
                    <span className="ml-2 inline-flex items-center gap-1 text-[10px] font-semibold text-[#5fe08a]">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#5fe08a]" />
                      {t("logs.live")}
                    </span>
                  ) : null}
                  <span className="flex-1 text-center font-mono text-[11px] text-zinc-500">
                    task-logs · kb_name={kbName} — {shell}
                  </span>
                  <span className="font-mono text-[10px] text-zinc-600">EN</span>
                </div>
                <div
                  ref={logRef}
                  className="max-h-[520px] min-h-[320px] overflow-auto px-4 py-3 font-mono text-[12px] leading-relaxed"
                >
                  {loadingLogs ? (
                    <div className="flex items-center gap-2 text-zinc-400">
                      <Spinner size="sm" />
                      {t("logs.loading")}
                    </div>
                  ) : logError ? (
                    <p className="text-[#ff7a7d]">{logError}</p>
                  ) : lines.length === 0 ? (
                    <p className="text-zinc-500">{t("logs.empty")}</p>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      {lines.map((line, i) =>
                        line.kind === "error" ? (
                          <span
                            // biome-ignore lint/suspicious/noArrayIndexKey: logs render in order, no stable id
                            key={i}
                            className="-mx-4 flex items-start gap-1.5 bg-[#ff383c1f] px-4 py-0.5 font-medium text-[#ff7a7d]"
                          >
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                            <span className="whitespace-pre-wrap break-words">
                              {line.ts ? <span className="opacity-70">[{line.ts}] </span> : null}
                              {line.level ? `[${line.level}] ` : ""}
                              {line.source ? `[${line.source}] ` : ""}
                              {line.message}
                            </span>
                          </span>
                        ) : (
                          <span
                            // biome-ignore lint/suspicious/noArrayIndexKey: logs render in order, no stable id
                            key={i}
                            className={cn("whitespace-pre-wrap break-words", KIND_CLASS[line.kind])}
                          >
                            {line.ts ? <span className="text-zinc-600">[{line.ts}] </span> : null}
                            {line.level ? `[${line.level}] ` : ""}
                            {line.source ? `[${line.source}] ` : ""}
                            {line.message}
                          </span>
                        ),
                      )}
                      <span className="mt-1 text-[#5fe08a]">
                        $ <span className="animate-pulse">▌</span>{" "}
                        <span className="text-zinc-600">task-logs</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <span className="font-mono text-[11px] text-foreground-tertiary">{footerMeta}</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onPress={copyLogs}>
                  {copied ? (
                    <Check className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Copy className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {copied ? t("logs.copied") : t("logs.copyLogs")}
                </Button>
                {isFailed ? (
                  <Button
                    variant="danger"
                    size="sm"
                    onPress={() => {
                      onRetry(snapshot);
                      state.close();
                    }}
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                    {t("logs.retryTask")}
                  </Button>
                ) : (
                  <Button variant="primary" size="sm" onPress={state.close}>
                    <X className="h-3.5 w-3.5" aria-hidden />
                    {t("logs.close")}
                  </Button>
                )}
              </div>
            </div>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
