"use client";

import type { QuerySources } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Modal } from "@heroui/react";
import { Eye, Layers, ListTree, Maximize2, Minimize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DocumentStructureTree } from "./DocumentStructureTree";
import { FilePreview } from "./FilePreview";
import { type SourceFileTab, SourceFileTabs } from "./SourceFileTabs";
import { TextSourceCard } from "./TextSourceCard";
import { VisualSourceCard } from "./VisualSourceCard";
import { flattenSources, sourceDocumentId, sourceFileName, sourceString } from "./sources-utils";
import type { FlatSource, PanelLayout, PreviewTarget } from "./types";

interface SourcesPanelProps {
  sources: QuerySources | null | undefined;
  onImageClick: (imageId: string) => void;
  /** 1-based flat index highlighted by a citation click, or null. */
  highlightIndex: number | null;
  /** External request to open the preview tab (e.g. rerank visual_top thumb). */
  previewIntent?: PreviewTarget | null;
  /** Increment to re-apply `previewIntent` even when the target is unchanged. */
  previewIntentKey?: number;
}

type RailView = "sources" | "structure" | "preview";

function fileKeyOf(item: FlatSource): { key: string; name: string } {
  const name = sourceFileName(item.source);
  if (name) return { key: name, name };
  const page = sourceString(item.source, "page");
  const fallback = page ? `p.${page}` : `#${item.index}`;
  return { key: fallback, name: fallback };
}

/**
 * SourcesPanel — the RAG evidence workbench. Three co-equal surfaces share the
 * right rail: Sources (rich text/visual cards with anchors), Structure (the
 * document's parsed semantic tree with retrieved nodes highlighted), and
 * Preview (image / table HTML / PDF / original file). Citations and card
 * actions drive focus across all three. Expands into a centred glass-modal for
 * full-content reading.
 */
export function SourcesPanel({
  sources,
  onImageClick,
  highlightIndex,
  previewIntent = null,
  previewIntentKey = 0,
}: SourcesPanelProps) {
  const t = useTranslations("qa.sources");
  const tRail = useTranslations("qa.rail");
  const flat = useMemo(() => flattenSources(sources), [sources]);
  const refs = useRef<Map<number, HTMLDivElement>>(new Map());
  const consumedPreviewKey = useRef(0);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [view, setView] = useState<RailView>("sources");
  const [structureDoc, setStructureDoc] = useState<string | null>(null);
  const [structureFocus, setStructureFocus] = useState<string | null>(null);
  const [previewTarget, setPreviewTarget] = useState<PreviewTarget | null>(null);
  const [expanded, setExpanded] = useState(false);

  const registerRef = useCallback((index: number, el: HTMLDivElement | null) => {
    if (el) refs.current.set(index, el);
    else refs.current.delete(index);
  }, []);

  const files = useMemo<SourceFileTab[]>(() => {
    const seen = new Set<string>();
    const out: SourceFileTab[] = [];
    for (const item of flat) {
      const { key, name } = fileKeyOf(item);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ key, name, type: item.type, firstIndex: item.index });
    }
    return out;
  }, [flat]);

  // Default the active file tab and structure document when the source set changes.
  useEffect(() => {
    setActiveKey(files[0]?.key ?? null);
    const firstDoc = flat.map((f) => sourceDocumentId(f.source)).find(Boolean) ?? null;
    setStructureDoc(firstDoc);
    setStructureFocus(null);
    const previewActive = previewIntentKey > 0 && previewIntentKey === consumedPreviewKey.current;
    if (!previewActive) {
      setPreviewTarget(null);
      setView("sources");
    }
  }, [files, flat, previewIntentKey]);

  const scrollToIndex = useCallback((index: number) => {
    const el = refs.current.get(index);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  // Follow citation clicks or external preview intents in the evidence rail.
  useEffect(() => {
    if (previewIntent && previewIntentKey > 0 && previewIntentKey !== consumedPreviewKey.current) {
      consumedPreviewKey.current = previewIntentKey;
      setPreviewTarget(previewIntent);
      setView("preview");
      if (highlightIndex != null) {
        const item = flat.find((f) => f.index === highlightIndex);
        if (item) setActiveKey(fileKeyOf(item).key);
      }
      return;
    }

    if (highlightIndex == null) return;
    const item = flat.find((f) => f.index === highlightIndex);
    if (!item) return;
    const docId = sourceDocumentId(item.source);
    const focus =
      item.type === "image"
        ? sourceString(item.source, "parent_section")
        : sourceString(item.source, "path");
    if (docId) {
      setStructureDoc(docId);
      setStructureFocus(focus || null);
      setView("structure");
    } else {
      setView("sources");
      setActiveKey(fileKeyOf(item).key);
      scrollToIndex(highlightIndex);
    }
  }, [highlightIndex, previewIntent, previewIntentKey, flat, scrollToIndex]);

  const handleSelectTab = useCallback(
    (file: SourceFileTab) => {
      setActiveKey(file.key);
      scrollToIndex(file.firstIndex);
    },
    [scrollToIndex],
  );

  const handleViewStructure = useCallback((documentId: string, path?: string) => {
    setStructureDoc(documentId);
    setStructureFocus(path ?? null);
    setView("structure");
  }, []);

  const handlePreview = useCallback((target: PreviewTarget) => {
    setPreviewTarget(target);
    setView("preview");
  }, []);

  const highlightPaths = useMemo(() => {
    const set = new Set<string>();
    if (!structureDoc) return set;
    for (const f of flat) {
      if (sourceDocumentId(f.source) !== structureDoc) continue;
      const path =
        f.type === "image"
          ? sourceString(f.source, "parent_section")
          : sourceString(f.source, "path");
      if (path) set.add(path);
    }
    return set;
  }, [flat, structureDoc]);

  const shellProps = {
    view,
    setView,
    flatCount: flat.length,
    structureDoc,
    previewTarget,
    expanded,
    onExpand: () => setExpanded(true),
    onCollapse: () => setExpanded(false),
  };

  const bodyProps = {
    view,
    layout: (expanded ? "expanded" : "rail") as PanelLayout,
    flat,
    files,
    activeKey,
    highlightIndex,
    structureDoc,
    structureFocus,
    highlightPaths,
    previewTarget,
    registerRef,
    onImageClick,
    onSelectTab: handleSelectTab,
    onViewStructure: handleViewStructure,
    onPreview: handlePreview,
  };

  return (
    <>
      <aside className="h-full min-h-0">
        {!expanded ? (
          <SourcesPanelShell layout="rail" {...shellProps}>
            <SourcesPanelBody {...bodyProps} layout="rail" />
          </SourcesPanelShell>
        ) : (
          <div aria-hidden className="h-full rounded-3xl border border-border/40 bg-surface/50" />
        )}
      </aside>

      <Modal isOpen={expanded} onOpenChange={setExpanded}>
        <Modal.Backdrop className="bg-background/45 backdrop-blur-2xl backdrop-saturate-150 data-[entering]:duration-350 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-250 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
          <Modal.Container>
            <Modal.Dialog
              aria-label={t("title")}
              className="flex h-[min(88vh,920px)] w-[min(1200px,94vw)] max-w-[94vw] flex-col overflow-hidden rounded-3xl border border-border/80 bg-surface/95 shadow-[0_32px_96px_-16px_rgba(15,23,42,0.28)] ring-1 ring-white/60 backdrop-blur-xl data-[entering]:duration-350 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-250 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
            >
              <SourcesPanelShell layout="expanded" {...shellProps}>
                <SourcesPanelBody {...bodyProps} layout="expanded" />
              </SourcesPanelShell>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </>
  );
}

interface SourcesPanelShellProps {
  layout: PanelLayout;
  view: RailView;
  setView: (view: RailView) => void;
  flatCount: number;
  structureDoc: string | null;
  previewTarget: PreviewTarget | null;
  expanded: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  children: React.ReactNode;
}

function SourcesPanelShell({
  layout,
  view,
  setView,
  flatCount,
  structureDoc,
  previewTarget,
  expanded,
  onExpand,
  onCollapse,
  children,
}: SourcesPanelShellProps) {
  const t = useTranslations("qa.sources");
  const tRail = useTranslations("qa.rail");
  const isExpanded = layout === "expanded";

  const tabs: { id: RailView; label: string; icon: typeof Layers; disabled?: boolean }[] = [
    { id: "sources", label: tRail("sources"), icon: Layers },
    { id: "structure", label: tRail("structure"), icon: ListTree, disabled: !structureDoc },
    { id: "preview", label: tRail("preview"), icon: Eye, disabled: !previewTarget },
  ];

  return (
    <div
      className={cn(
        "ai-scope flex h-full min-h-0 flex-col overflow-hidden",
        !isExpanded &&
          "rounded-3xl border border-border bg-surface shadow-[0_2px_8px_0_rgba(0,0,0,0.04)]",
      )}
    >
      <header className="shrink-0 border-border/70 border-b bg-surface/80 px-4 pt-3 backdrop-blur-sm sm:px-5">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-semibold text-foreground text-sm">{t("title")}</p>
          </div>
          <IconTipButton
            label={expanded ? tRail("collapse") : tRail("expand")}
            onClick={expanded ? onCollapse : onExpand}
          >
            {expanded ? (
              <Minimize2 size={15} strokeWidth={2} aria-hidden />
            ) : (
              <Maximize2 size={15} strokeWidth={2} aria-hidden />
            )}
          </IconTipButton>
        </div>

        <nav className="flex items-stretch gap-5" role="tablist" aria-label={t("title")}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = view === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                disabled={tab.disabled}
                onClick={() => setView(tab.id)}
                className={cn(
                  "relative -mb-px inline-flex items-center gap-1.5 pb-2.5 pt-1 font-medium text-[13px] transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2",
                  "disabled:cursor-not-allowed disabled:opacity-40",
                  active
                    ? "text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent"
                    : "text-foreground-tertiary hover:text-foreground-secondary",
                )}
              >
                <Icon
                  size={15}
                  strokeWidth={active ? 2.25 : 2}
                  aria-hidden
                  className={cn("shrink-0", active ? "text-accent" : "text-foreground-tertiary")}
                />
                <span>{tab.label}</span>
                {tab.id === "sources" && flatCount > 0 ? (
                  <span
                    className={cn(
                      "rounded-md px-1.5 py-px font-mono text-[10px] tabular-nums",
                      active
                        ? "bg-accent-soft text-accent-soft-foreground"
                        : "bg-(--surface-muted) text-foreground-tertiary",
                    )}
                  >
                    {flatCount}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>
      </header>

      {children}
    </div>
  );
}

interface SourcesPanelBodyProps {
  layout: PanelLayout;
  view: RailView;
  flat: FlatSource[];
  files: SourceFileTab[];
  activeKey: string | null;
  highlightIndex: number | null;
  structureDoc: string | null;
  structureFocus: string | null;
  highlightPaths: Set<string>;
  previewTarget: PreviewTarget | null;
  registerRef: (index: number, el: HTMLDivElement | null) => void;
  onImageClick: (imageId: string) => void;
  onSelectTab: (file: SourceFileTab) => void;
  onViewStructure: (documentId: string, path?: string) => void;
  onPreview: (target: PreviewTarget) => void;
}

function SourcesPanelBody({
  layout,
  view,
  flat,
  files,
  activeKey,
  highlightIndex,
  structureDoc,
  structureFocus,
  highlightPaths,
  previewTarget,
  registerRef,
  onImageClick,
  onSelectTab,
  onViewStructure,
  onPreview,
}: SourcesPanelBodyProps) {
  const pad = layout === "expanded" ? "px-6 py-5" : "px-4 py-4";

  if (view === "sources") {
    if (flat.length === 0) return <EmptyState layout={layout} />;
    return (
      <div
        className={cn(
          "min-h-0 flex-1 overflow-y-auto",
          pad,
          layout === "expanded" ? "space-y-5" : "space-y-4",
        )}
      >
        <SourceFileTabs files={files} activeKey={activeKey} onSelect={onSelectTab} />
        {flat.map((item) =>
          item.type === "image" ? (
            <VisualSourceCard
              key={item.index}
              item={item}
              highlighted={highlightIndex === item.index}
              layout={layout}
              onImageClick={onImageClick}
              registerRef={registerRef}
              onViewStructure={onViewStructure}
              onPreview={onPreview}
            />
          ) : (
            <TextSourceCard
              key={item.index}
              item={item}
              highlighted={highlightIndex === item.index}
              layout={layout}
              registerRef={registerRef}
              onViewStructure={onViewStructure}
              onPreview={onPreview}
            />
          ),
        )}
      </div>
    );
  }

  if (view === "structure") {
    return (
      <div className={cn("min-h-0 flex-1 overflow-y-auto", pad)}>
        <DocumentStructureTree
          documentId={structureDoc}
          highlightPaths={highlightPaths}
          focusPath={structureFocus}
          onImageClick={onImageClick}
          onPreview={onPreview}
        />
      </div>
    );
  }

  if (view === "preview") {
    return (
      <div className={cn("min-h-0 flex-1 overflow-y-auto", pad)}>
        <FilePreview target={previewTarget} layout={layout} onImageClick={onImageClick} />
      </div>
    );
  }

  return null;
}

function IconTipButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        "group relative inline-flex size-7 shrink-0 items-center justify-center rounded-md",
        "text-foreground-tertiary transition-colors hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2",
      )}
    >
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute top-[calc(100%+6px)] right-0 z-20 whitespace-nowrap",
          "rounded-md border border-border/50 bg-surface px-2 py-1",
          "font-medium text-[11px] text-foreground-secondary",
          "opacity-0 shadow-[0_4px_12px_rgba(15,23,42,0.08)] transition-opacity duration-150",
          "group-hover:opacity-100 group-focus-visible:opacity-100",
        )}
      >
        {label}
      </span>
    </button>
  );
}

function EmptyState({ layout }: { layout: PanelLayout }) {
  const t = useTranslations("qa.sources");
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center gap-3 text-center",
        layout === "expanded" ? "px-12 py-16" : "px-8",
      )}
    >
      <span
        aria-hidden
        className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-(--surface-muted) text-foreground-tertiary"
      >
        <Layers size={22} strokeWidth={1.8} />
      </span>
      <p className="font-medium text-foreground-secondary text-sm">{t("empty")}</p>
      <p
        className={cn(
          "text-foreground-tertiary text-xs leading-relaxed",
          layout === "expanded" ? "max-w-md" : "max-w-60",
        )}
      >
        {t("emptyHint")}
      </p>
    </div>
  );
}
