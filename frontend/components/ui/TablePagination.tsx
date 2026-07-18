"use client";

import { cn } from "@/components/ui/cn";
import { ChevronLeft, ChevronRight } from "lucide-react";

export const TABLE_PAGE_SIZES = [10, 20, 50] as const;

export interface TablePaginationProps {
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
  totalLabel: string;
  perPageLabel: string;
}

/**
 * Shared list footer: total count, page buttons, and page-size select.
 * Used by ingest TaskTable and KB detail document / log tables.
 */
export function TablePagination({
  total,
  page,
  pageSize,
  onPage,
  onPageSize,
  totalLabel,
  perPageLabel,
}: TablePaginationProps) {
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
          {TABLE_PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
