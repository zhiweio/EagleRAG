"use client";

import { useDocuments } from "@/lib/hooks/useDocuments";
import type { Document } from "@/lib/types";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef } from "react";

interface MentionAutocompleteProps {
  /** Whether the @ mention popover should be visible. */
  active: boolean;
  /** The filter text typed after @ (may be empty to show all). */
  query: string;
  /** Currently highlighted row index (0-based), controlled by the composer. */
  activeIndex: number;
  /** Knowledge-base filter applied to the document search (null = all). */
  kbName?: string | null;
  /** Called when a document is picked (click or Enter). */
  onSelect: (doc: Document) => void;
  /** Notifies the parent of the current result set so it can clamp activeIndex. */
  onItemsChange: (items: Document[]) => void;
}

/**
 * Floating document picker shown above the composer while the user types an
 * `@mention`. Fetches `/documents?q=…` via the `useDocuments` hook (react-query
 * cache is auto-isolated when the queryKey (incl. q/kb_name) changes) and renders
 * a compact list. Keyboard navigation (up/down/enter) is owned by the composer
 * via `activeIndex`; this component only renders rows and reports the count back.
 */
export function MentionAutocomplete({
  active,
  query,
  activeIndex,
  kbName,
  onSelect,
  onItemsChange,
}: MentionAutocompleteProps) {
  const t = useTranslations("qa");
  // Always enable the query to leverage the react-query cache; queryKey includes q and kb_name for automatic isolation.
  const documentsQuery = useDocuments({
    q: query || undefined,
    kb_name: kbName || undefined,
    limit: 8,
  });
  // Stable items ref — avoids ?? [] creating a new array each render and triggering an effect loop.
  const items = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data?.items]);
  const loading = documentsQuery.isLoading;

  // Hold the callback in a ref so onItemsChange isn't an effect dependency that causes extra runs.
  const onItemsChangeRef = useRef(onItemsChange);
  onItemsChangeRef.current = onItemsChange;

  // Report the current result set back to the composer so it can clamp activeIndex; clear when inactive.
  useEffect(() => {
    if (!active) {
      onItemsChangeRef.current([]);
      return;
    }
    onItemsChangeRef.current(items);
  }, [active, items]);

  if (!active) return null;

  return (
    <div className="absolute bottom-full left-0 z-20 mb-2 w-full max-w-md overflow-hidden rounded-lg border border-border bg-surface shadow-overlay">
      {loading && items.length === 0 ? (
        <p className="px-3 py-2 text-xs text-muted">{t("composer.mentionLoading")}</p>
      ) : items.length === 0 ? (
        <p className="px-3 py-2 text-xs text-muted">{t("composer.mentionEmpty")}</p>
      ) : (
        <ul className="max-h-60 overflow-y-auto py-1">
          {items.map((doc, i) => (
            <li key={doc.document_id}>
              <button
                type="button"
                data-active={i === activeIndex ? "" : undefined}
                onMouseDown={(e) => {
                  // prevent the textarea from blurring before the click resolves
                  e.preventDefault();
                  onSelect(doc);
                }}
                className={
                  i === activeIndex
                    ? "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm bg-accent-soft text-accent"
                    : "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-foreground hover:bg-background-secondary"
                }
              >
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded bg-background-secondary text-[10px] font-semibold text-muted">
                  {(doc.source_type ?? "??").slice(0, 2).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1 truncate">{doc.name}</span>
                <span className="shrink-0 text-[10px] text-muted">{doc.pipeline}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
