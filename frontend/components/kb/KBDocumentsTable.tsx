"use client";

import { PipelineBadge } from "@/components/ingest/PipelineBadge";
import { DocStatusDot, FileBadge, docStatusKey } from "@/components/kb/kb-visuals";
import { TablePagination, cn } from "@/components/ui";
import { formatRelative } from "@/lib/kb/types";
import type { Document } from "@/lib/types";
import { Skeleton } from "@heroui/react";
import { Eye, Inbox, Trash2, Upload } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

const GRID = "grid-cols-[minmax(0,1.4fr)_140px_88px_112px_100px_88px]";

const STATUS_TEXT: Record<string, string> = {
  ready: "text-success",
  active: "text-warning",
  failed: "text-danger",
  idle: "text-foreground-tertiary",
};

function DocStatusLabel({ status }: { status: string }) {
  const t = useTranslations("kb.detail.docStatus");
  const key = docStatusKey(status);
  const label =
    key === "ready"
      ? t("ready")
      : key === "active"
        ? t("active")
        : key === "failed"
          ? t("failed")
          : t("idle");
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs font-bold", STATUS_TEXT[key])}>
      <DocStatusDot status={status} />
      {label}
    </span>
  );
}

function DocumentRow({
  doc,
  onPreview,
  onDelete,
}: {
  doc: Document;
  onPreview: (doc: Document) => void;
  onDelete: (doc: Document) => void;
}) {
  const t = useTranslations("kb.detail.table");
  const locale = useLocale();
  const failed = docStatusKey(doc.status) === "failed";

  return (
    <div
      className={cn(
        "group grid items-center gap-3 border-b border-border/70 px-4 py-3 last:border-0",
        GRID,
      )}
      style={
        failed
          ? {
              backgroundColor: "var(--danger-soft)",
              boxShadow: "inset 3px 0 0 0 var(--danger)",
            }
          : undefined
      }
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <FileBadge name={doc.name} sourceUri={doc.source_uri} size={36} />
        <div className="flex min-w-0 flex-col gap-0.5">
          <button
            type="button"
            onClick={() => onPreview(doc)}
            className="truncate text-left text-sm font-semibold text-foreground hover:text-accent"
            title={doc.name}
          >
            {doc.name}
          </button>
          <span
            className="truncate font-mono text-[10px] text-foreground-tertiary"
            title={doc.document_id}
          >
            {doc.document_id.length > 16 ? `${doc.document_id.slice(0, 16)}…` : doc.document_id}
          </span>
        </div>
      </div>

      <div className="min-w-0">
        <PipelineBadge pipeline={doc.pipeline} />
      </div>

      <div className="flex flex-col">
        <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
          {doc.chunk_count == null ? "—" : doc.chunk_count.toLocaleString()}
        </span>
        <span className="text-[10px] text-foreground-tertiary">{t("chunks")}</span>
      </div>

      <DocStatusLabel status={doc.status} />

      <span className="text-xs text-foreground-tertiary">
        {doc.updated_at
          ? formatRelative(Date.now() - new Date(String(doc.updated_at)).getTime(), locale)
          : "—"}
      </span>

      <div className="flex items-center justify-end gap-1">
        <button
          type="button"
          aria-label={t("preview")}
          onClick={() => onPreview(doc)}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-foreground-tertiary transition-colors hover:bg-accent/10 hover:text-accent"
        >
          <Eye className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          aria-label={t("delete")}
          onClick={() => onDelete(doc)}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-foreground-tertiary transition-colors hover:bg-danger/10 hover:text-danger"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}

export interface KBDocumentsTableProps {
  documents: Document[];
  total: number;
  loading: boolean;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onPreview: (doc: Document) => void;
  onDelete: (doc: Document) => void;
  onUpload: () => void;
}

/**
 * KB detail Documents tab — denser ops ledger aligned with ingest TaskTable:
 * grid columns, status tint on failures, shared TablePagination.
 */
export function KBDocumentsTable({
  documents,
  total,
  loading,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  onPreview,
  onDelete,
  onUpload,
}: KBDocumentsTableProps) {
  const t = useTranslations("kb.detail");

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <span className="text-xs font-medium text-foreground-tertiary">
          {t("table.count", { count: total })}
        </span>
        <button
          type="button"
          onClick={onUpload}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-(--surface-muted)"
        >
          <Upload className="h-3.5 w-3.5" aria-hidden />
          {t("table.upload")}
        </button>
      </div>

      <div
        className={cn(
          "grid gap-3 border-b border-border px-4 py-2.5 text-[11px] font-medium text-foreground-tertiary",
          GRID,
        )}
      >
        <span>{t("table.name")}</span>
        <span>{t("table.pipeline")}</span>
        <span>{t("table.chunks")}</span>
        <span>{t("table.status")}</span>
        <span>{t("table.updated")}</span>
        <span className="text-right">{t("table.actions")}</span>
      </div>

      {loading ? (
        <div className="flex flex-col">
          {["sk-0", "sk-1", "sk-2", "sk-3", "sk-4"].map((key) => (
            <div key={key} className={cn("grid items-center gap-3 px-4 py-3.5", GRID)}>
              <Skeleton className="h-8 w-full max-w-64 rounded" />
              <Skeleton className="h-5 w-24 rounded" />
              <Skeleton className="h-4 w-12 rounded" />
              <Skeleton className="h-4 w-16 rounded" />
              <Skeleton className="h-4 w-14 rounded" />
              <Skeleton className="ml-auto h-6 w-14 rounded" />
            </div>
          ))}
        </div>
      ) : total === 0 ? (
        <div className="flex flex-col items-center gap-3 py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-background-secondary text-foreground-tertiary">
            <Inbox className="h-6 w-6" aria-hidden />
          </span>
          <p className="max-w-sm text-sm text-foreground-tertiary">{t("table.empty")}</p>
          <button
            type="button"
            onClick={onUpload}
            className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-colors hover:bg-accent-hover"
          >
            <Upload className="h-4 w-4" aria-hidden />
            {t("table.upload")}
          </button>
        </div>
      ) : (
        <div className="flex flex-col">
          {documents.map((doc) => (
            <DocumentRow
              key={doc.document_id}
              doc={doc}
              onPreview={onPreview}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}

      {!loading && total > 0 ? (
        <TablePagination
          total={total}
          page={page}
          pageSize={pageSize}
          onPage={onPageChange}
          onPageSize={onPageSizeChange}
          totalLabel={t("pagination.total", { count: total })}
          perPageLabel={t("pagination.perPage")}
        />
      ) : null}
    </div>
  );
}
