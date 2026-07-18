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
import { TablePagination, cn } from "@/components/ui";
import type { Task } from "@/lib/types";
import { Button, Skeleton } from "@heroui/react";
import { FileImage, Inbox, RefreshCw, RotateCcw, X } from "lucide-react";
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
  hideKbBadge,
}: {
  task: Task;
  onRetry: (task: Task) => void;
  onDelete: (task: Task) => void;
  onViewLogs: (task: Task) => void;
  cancelLabel: string;
  retryLabel: string;
  hideKbBadge?: boolean;
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
      <button
        type="button"
        onClick={() => onViewLogs(task)}
        className="text-left font-mono text-xs text-foreground-secondary hover:text-accent"
        title={task.job_id}
      >
        {task.job_id.length > 12 ? `${task.job_id.slice(0, 12)}…` : task.job_id}
      </button>

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
          {!hideKbBadge && task.kb_name ? (
            <span className="inline-flex w-fit items-center rounded bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[10px] text-foreground-tertiary">
              kb_name: {task.kb_name}
            </span>
          ) : null}
        </div>
      </div>

      <div className="min-w-0">
        <PipelineBadge pipeline={task.pipeline} />
      </div>

      <div>
        <StatusPill phase={phase} label={stateLabel(task)} />
      </div>

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

interface TaskTableProps {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  onRetry: (task: Task) => void;
  onDelete: (task: Task) => void;
  onViewLogs: (task: Task) => void;
  onRetryLoad: () => void;
  /** When set with page handlers, pagination is server-driven. */
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  /** Hide per-row kb_name chip (e.g. KB detail already scopes the list). */
  hideKbBadge?: boolean;
  emptyHint?: string;
}

export function TaskTable({
  tasks,
  loading,
  error,
  onRetry,
  onDelete,
  onViewLogs,
  onRetryLoad,
  total: totalProp,
  page: pageProp,
  pageSize: pageSizeProp,
  onPageChange,
  onPageSizeChange,
  hideKbBadge,
  emptyHint,
}: TaskTableProps) {
  const t = useTranslations("ingest");
  const serverPaged = onPageChange != null && onPageSizeChange != null;
  const [localPage, setLocalPage] = useState(1);
  const [localPageSize, setLocalPageSize] = useState(10);

  const page = serverPaged ? (pageProp ?? 1) : localPage;
  const pageSize = serverPaged ? (pageSizeProp ?? 10) : localPageSize;
  const total = serverPaged ? (totalProp ?? tasks.length) : tasks.length;

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  useEffect(() => {
    if (!serverPaged && localPage > pageCount) setLocalPage(1);
  }, [serverPaged, localPage, pageCount]);

  const paged = serverPaged ? tasks : tasks.slice((page - 1) * pageSize, page * pageSize);

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
      ) : total === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
          <Inbox className="h-8 w-8 text-foreground-tertiary" aria-hidden />
          <p className="text-sm font-medium text-foreground">{t("table.empty")}</p>
          <p className="text-xs text-foreground-secondary">{emptyHint ?? t("table.emptyHint")}</p>
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
              hideKbBadge={hideKbBadge}
            />
          ))}
        </div>
      )}

      {!loading && total > 0 ? (
        <TablePagination
          total={total}
          page={page}
          pageSize={pageSize}
          onPage={(next) => {
            if (serverPaged) onPageChange?.(next);
            else setLocalPage(next);
          }}
          onPageSize={(size) => {
            if (serverPaged) {
              onPageSizeChange?.(size);
              return;
            }
            setLocalPageSize(size);
            setLocalPage(1);
          }}
          totalLabel={t("pagination.total", { count: total })}
          perPageLabel={t("pagination.perPage")}
        />
      ) : null}
    </div>
  );
}
