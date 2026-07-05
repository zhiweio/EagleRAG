"use client";

import { PipelineBadge } from "@/components/ingest/PipelineBadge";
import { StatusPill } from "@/components/ingest/StatusPill";
import {
  type TaskPhase,
  documentName,
  normalizeStatus,
  pipelineKind,
  progressPercent,
  stateLabel,
} from "@/components/ingest/status";
import { FileBadge } from "@/components/kb/kb-visuals";
import { cn } from "@/components/ui";
import type { Task } from "@/lib/types";
import { Button, Skeleton } from "@heroui/react";
import { ChevronLeft, ChevronRight, FileImage, Inbox, RefreshCw, RotateCcw, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

const GRID = "grid-cols-[104px_minmax(0,1fr)_150px_128px_minmax(0,1.1fr)_104px]";

/** Row tint + left border bar: pending amber / failed danger / others transparent. */
const ROW_TINT: Record<TaskPhase, { bg: string; border: string } | null> = {
  pending: { bg: "var(--warning-soft)", border: "var(--warning)" },
  failed: { bg: "var(--danger-soft)", border: "var(--danger)" },
  running: null,
  success: null,
};

const PROGRESS_FILL: Record<TaskPhase, string> = {
  pending: "bg-warning",
  running: "bg-accent",
  success: "bg-success",
  failed: "bg-danger",
};

function TaskRow({
  task,
  onRetry,
  onDelete,
  onViewLogs,
  cancelLabel,
  retryLabel,
}: {
  task: Task;
  onRetry: (task: Task) => void;
  onDelete: (task: Task) => void;
  onViewLogs: (task: Task) => void;
  cancelLabel: string;
  retryLabel: string;
}) {
  const phase = normalizeStatus(task.status);
  const pct = progressPercent(task);
  const isVisual = pipelineKind(task) === "pixelrag";
  const tint = ROW_TINT[phase];
  const note = task.error?.trim()
    ? task.error.trim()
    : task.total && task.current != null
      ? `${task.current}/${task.total}`
      : `${pct}%`;

  return (
    <div
      className={cn(
        "grid items-center gap-3 border-b border-border/70 px-4 py-3 last:border-0",
        GRID,
      )}
      style={
        tint ? { backgroundColor: tint.bg, boxShadow: `inset 3px 0 0 0 ${tint.border}` } : undefined
      }
    >
      {/* Task ID */}
      <button
        type="button"
        onClick={() => onViewLogs(task)}
        className="text-left font-mono text-xs text-foreground-secondary hover:text-accent"
        title={task.job_id}
      >
        {task.job_id.length > 12 ? `${task.job_id.slice(0, 12)}…` : task.job_id}
      </button>

      {/* Document */}
      <div className="flex min-w-0 items-center gap-2.5">
        <FileBadge
          name={documentName(task)}
          size={36}
          forceIcon={isVisual ? FileImage : undefined}
        />
        <div className="flex min-w-0 flex-col gap-0.5">
          <button
            type="button"
            onClick={() => onViewLogs(task)}
            className="truncate text-left text-sm font-semibold text-foreground hover:text-accent"
            title={documentName(task)}
          >
            {documentName(task)}
          </button>
          {task.kb_name ? (
            <span className="inline-flex w-fit items-center rounded bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[10px] text-foreground-tertiary">
              kb_name: {task.kb_name}
            </span>
          ) : null}
        </div>
      </div>

      {/* Pipeline */}
      <div className="min-w-0">
        <PipelineBadge pipeline={task.pipeline} />
      </div>

      {/* State */}
      <div>
        <StatusPill phase={phase} label={stateLabel(task)} />
      </div>

      {/* Progress */}
      <div className="flex min-w-0 flex-col gap-1.5">
        <span
          className={cn(
            "truncate text-[11px]",
            phase === "failed" ? "text-danger" : "text-foreground-secondary",
          )}
          title={note}
        >
          {note}
        </span>
        <span aria-hidden className="h-1 w-full overflow-hidden rounded-full bg-(--surface-muted)">
          <span
            className={cn("block h-full rounded-full", PROGRESS_FILL[phase])}
            style={{ width: `${pct}%` }}
          />
        </span>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end">
        {phase === "pending" ? (
          <button
            type="button"
            onClick={() => onDelete(task)}
            className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-1 text-[11px] font-semibold text-danger transition-colors hover:bg-danger-soft-hover"
          >
            <X className="h-3 w-3" aria-hidden />
            {cancelLabel}
          </button>
        ) : phase === "failed" ? (
          <button
            type="button"
            onClick={() => onRetry(task)}
            className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-semibold text-accent transition-colors hover:bg-accent-soft-hover"
          >
            <RotateCcw className="h-3 w-3" aria-hidden />
            {retryLabel}
          </button>
        ) : (
          <span className="text-sm text-foreground-tertiary">—</span>
        )}
      </div>
    </div>
  );
}

const PAGE_SIZES = [10, 20, 50];

function Pagination({
  total,
  page,
  pageSize,
  onPage,
  onPageSize,
  totalLabel,
  perPageLabel,
}: {
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
  totalLabel: string;
  perPageLabel: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pages: (number | "…")[] = [];
  for (let i = 1; i <= pageCount; i += 1) {
    if (i === 1 || i === pageCount || Math.abs(i - page) <= 1) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "…") {
      pages.push("…");
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
      <span className="text-xs text-foreground-secondary">{totalLabel}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label="prev"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-foreground-secondary transition-colors hover:bg-(--surface-muted) disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </button>
        {pages.map((p, i) =>
          p === "…" ? (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: ellipsis placeholder
              key={`ellipsis-${i}`}
              className="px-1 text-xs text-foreground-tertiary"
            >
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onPage(p)}
              className={cn(
                "inline-flex h-7 min-w-7 items-center justify-center rounded-md px-1.5 text-xs font-medium transition-colors",
                p === page
                  ? "bg-accent text-accent-foreground"
                  : "text-foreground-secondary hover:bg-(--surface-muted)",
              )}
            >
              {p}
            </button>
          ),
        )}
        <button
          type="button"
          disabled={page >= pageCount}
          onClick={() => onPage(page + 1)}
          aria-label="next"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-foreground-secondary transition-colors hover:bg-(--surface-muted) disabled:opacity-40"
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <label className="flex items-center gap-2 text-xs text-foreground-secondary">
        {perPageLabel}
        <select
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
          className="rounded-md border border-border bg-surface px-2 py-1 text-xs font-medium text-foreground outline-none"
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

interface TaskTableProps {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  onRetry: (task: Task) => void;
  onDelete: (task: Task) => void;
  onViewLogs: (task: Task) => void;
  onRetryLoad: () => void;
}

export function TaskTable({
  tasks,
  loading,
  error,
  onRetry,
  onDelete,
  onViewLogs,
  onRetryLoad,
}: TaskTableProps) {
  const t = useTranslations("ingest");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const pageCount = Math.max(1, Math.ceil(tasks.length / pageSize));
  useEffect(() => {
    if (page > pageCount) setPage(1);
  }, [page, pageCount]);

  const paged = tasks.slice((page - 1) * pageSize, page * pageSize);

  if (error && !loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        <p className="text-sm text-danger">{error}</p>
        <Button variant="outline" size="sm" onPress={onRetryLoad}>
          <RefreshCw className="h-4 w-4" aria-hidden />
          {t("table.retryLoad")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div
        className={cn(
          "grid gap-3 border-b border-border px-4 py-2.5 text-[11px] font-medium text-foreground-tertiary",
          GRID,
        )}
      >
        <span>{t("table.jobId")}</span>
        <span>{t("table.document")}</span>
        <span>{t("table.pipeline")}</span>
        <span>{t("table.state")}</span>
        <span>{t("table.progress")}</span>
        <span className="text-right">{t("table.actions")}</span>
      </div>

      {/* Body */}
      {loading ? (
        <div className="flex flex-col">
          {["sk-0", "sk-1", "sk-2", "sk-3", "sk-4"].map((key) => (
            <div key={key} className={cn("grid items-center gap-3 px-4 py-3.5", GRID)}>
              <Skeleton className="h-4 w-16 rounded" />
              <Skeleton className="h-8 w-full max-w-56 rounded" />
              <Skeleton className="h-5 w-24 rounded" />
              <Skeleton className="h-4 w-20 rounded" />
              <Skeleton className="h-4 w-full max-w-32 rounded" />
              <Skeleton className="ml-auto h-6 w-16 rounded-full" />
            </div>
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
          <Inbox className="h-8 w-8 text-foreground-tertiary" aria-hidden />
          <p className="text-sm font-medium text-foreground">{t("table.empty")}</p>
          <p className="text-xs text-foreground-secondary">{t("table.emptyHint")}</p>
        </div>
      ) : (
        <div className="flex flex-col">
          {paged.map((task) => (
            <TaskRow
              key={task.job_id}
              task={task}
              onRetry={onRetry}
              onDelete={onDelete}
              onViewLogs={onViewLogs}
              cancelLabel={t("table.cancel")}
              retryLabel={t("table.retry")}
            />
          ))}
        </div>
      )}

      {/* Footer */}
      {!loading && tasks.length > 0 ? (
        <Pagination
          total={tasks.length}
          page={page}
          pageSize={pageSize}
          onPage={setPage}
          onPageSize={(size) => {
            setPageSize(size);
            setPage(1);
          }}
          totalLabel={t("pagination.total", { count: tasks.length })}
          perPageLabel={t("pagination.perPage")}
        />
      ) : null}
    </div>
  );
}
