"use client";

import { useDocuments } from "@/lib/hooks/useDocuments";
import { prefetchPreviewResource } from "@/lib/hooks/usePreviewResource";
import { usePreviewStore } from "@/lib/stores/previewStore";
import { useUIStore } from "@/lib/stores/uiStore";
import type { Document } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Modal } from "@heroui/react";
import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

function Kbd({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-[18px] items-center rounded border border-border bg-surface px-1.5 font-mono text-[11px] font-semibold text-foreground-secondary">
      {children}
    </span>
  );
}

function Hint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="flex items-center gap-[3px]">
        {keys.map((k) => (
          <Kbd key={k}>{k}</Kbd>
        ))}
      </span>
      <span className="text-[11px] font-medium text-foreground-tertiary">{label}</span>
    </span>
  );
}

function openDocumentPreview(doc: Document, queryClient: QueryClient) {
  const target = {
    kind: "file" as const,
    documentId: doc.document_id,
    title: doc.name,
    sourceType: doc.source_type ?? null,
    sourceUri: doc.source_uri ?? null,
  };
  prefetchPreviewResource(queryClient, target);
  usePreviewStore.getState().openPreview(target, queryClient);
}

/**
 * GlobalSearchModal — centered command-palette search over the document registry.
 * Opened from the AppBar trigger or Cmd/Ctrl+K. Results open in the in-app preview modal.
 */
export function GlobalSearchModal() {
  const t = useTranslations("globalSearch");
  const queryClient = useQueryClient();
  const open = useUIStore((s) => s.globalSearchOpen);
  const setGlobalSearchOpen = useUIStore((s) => s.setGlobalSearchOpen);

  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const documentsQuery = useDocuments({
    q: debouncedQuery || undefined,
    limit: 20,
  });
  const items = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data?.items]);
  const loading = documentsQuery.isLoading;

  const close = useCallback(() => {
    setGlobalSearchOpen(false);
    setQuery("");
    setDebouncedQuery("");
    setActiveIndex(0);
  }, [setGlobalSearchOpen]);

  const selectItem = useCallback(
    (doc: Document) => {
      openDocumentPreview(doc, queryClient);
      close();
    },
    [close, queryClient],
  );

  useEffect(() => {
    if (!open) return;
    setActiveIndex(0);
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    setActiveIndex((i) => (items.length === 0 ? 0 : Math.min(i, items.length - 1)));
  }, [items.length]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (items.length === 0 ? 0 : Math.min(i + 1, items.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && items[activeIndex]) {
      e.preventDefault();
      selectItem(items[activeIndex]);
    }
  };

  return (
    <Modal isOpen={open} onOpenChange={(next) => !next && close()}>
      <Modal.Backdrop className="bg-black/30 backdrop-blur-md">
        <Modal.Container size="md" placement="center" scroll="inside">
          <Modal.Dialog className="max-w-xl overflow-hidden border border-border bg-surface p-0 shadow-overlay">
            <div onKeyDown={onKeyDown}>
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("placeholder")}
                  className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-secondary"
                  aria-label={t("placeholder")}
                />
              </div>

              <div className="max-h-[min(50vh,360px)] overflow-y-auto">
                {loading && items.length === 0 ? (
                  <p className="px-4 py-6 text-center text-sm text-foreground-tertiary">
                    {t("loading")}
                  </p>
                ) : items.length === 0 ? (
                  <p className="px-4 py-6 text-center text-sm text-foreground-tertiary">
                    {t("empty")}
                  </p>
                ) : (
                  <ul className="py-1">
                    {items.map((doc, i) => (
                      <li key={doc.document_id}>
                        <button
                          type="button"
                          onMouseDown={(e) => {
                            e.preventDefault();
                            selectItem(doc);
                          }}
                          className={cn(
                            "flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors",
                            i === activeIndex
                              ? "bg-accent-soft text-accent"
                              : "text-foreground hover:bg-background-secondary",
                          )}
                        >
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-background-secondary text-foreground-secondary">
                            <FileText className="h-4 w-4" aria-hidden />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{doc.name}</span>
                            <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-foreground-tertiary">
                              <span className="rounded bg-background-secondary px-1.5 py-0.5 font-medium">
                                {doc.kb_name}
                              </span>
                              {doc.status ? (
                                <span className="rounded bg-background-secondary px-1.5 py-0.5">
                                  {doc.status}
                                </span>
                              ) : null}
                              {doc.pipeline ? (
                                <span className="rounded bg-background-secondary px-1.5 py-0.5">
                                  {doc.pipeline}
                                </span>
                              ) : null}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-4 border-t border-border px-4 py-2.5">
                <Hint keys={["↑", "↓"]} label={t("hintNavigate")} />
                <Hint keys={["↵"]} label={t("hintOpen")} />
                <Hint keys={["esc"]} label={t("hintClose")} />
              </div>
            </div>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
