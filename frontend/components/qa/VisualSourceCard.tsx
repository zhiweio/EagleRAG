"use client";

import { imageUrl } from "@/lib/api/client";
import { ListTree, Maximize2, Sheet } from "lucide-react";
import { useTranslations } from "next-intl";
import { MarkdownSnippet } from "./MarkdownSnippet";
import { formatSim, sourceDocumentId, sourceString } from "./sources-utils";
import type { FlatSource, PanelLayout, PreviewTarget } from "./types";

interface VisualSourceCardProps {
  item: FlatSource;
  highlighted: boolean;
  layout?: PanelLayout;
  onImageClick: (imageId: string) => void;
  registerRef: (index: number, el: HTMLDivElement | null) => void;
  onViewStructure: (documentId: string, path?: string) => void;
  onPreview: (target: PreviewTarget) => void;
}

/**
 * VisualSourceCard — a PixelRAG / Knowhere visual tile with its semantic
 * anchors. Shows the chunk-type + page/position, the rendered image (click to
 * zoom), the Knowhere `content_summary`, the anchored `parent_section`, the
 * source chunk id and score, plus actions to open the tile or jump to its node
 * in the document's semantic tree.
 */
export function VisualSourceCard({
  item,
  highlighted,
  layout = "rail",
  onImageClick,
  registerRef,
  onViewStructure,
  onPreview,
}: VisualSourceCardProps) {
  const isExpanded = layout === "expanded";
  const t = useTranslations("qa.sources");
  const imageId = sourceString(item.source, "image_id");
  const page = sourceString(item.source, "page");
  const position = sourceString(item.source, "position");
  const chunkType = sourceString(item.source, "chunk_type");
  const parentSection = sourceString(item.source, "parent_section");
  const contentSummary = sourceString(item.source, "content_summary");
  const sourceChunkId = sourceString(item.source, "source_chunk_id");
  const documentId = sourceDocumentId(item.source);
  const sim = formatSim(item.source);
  const url = imageId ? imageUrl(imageId) : "";
  const meta = [page && `${t("page")} ${page}`, position].filter(Boolean).join(" · ");
  const typeLabel =
    chunkType === "image"
      ? t("imageChunk")
      : chunkType === "table"
        ? t("tableChunk")
        : t("pixelSlice");

  const open = () => {
    if (imageId) onImageClick(imageId);
    else if (documentId) onPreview({ kind: "file", documentId, title: t("pixelSlice") });
  };

  return (
    <div
      ref={(el) => registerRef(item.index, el)}
      className={`rounded-2xl border bg-surface transition-all duration-300 ${
        isExpanded ? "p-4" : "p-3"
      } ${
        highlighted
          ? "border-violet-400 ring-2 ring-violet-100"
          : "border-border hover:border-border/80"
      }`}
    >
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 px-1 font-mono text-[10px] text-violet-700">
            {item.index}
          </span>
          <span className="inline-flex shrink-0 items-center rounded-md bg-violet-100 px-2 py-0.5 font-medium text-[11px] text-violet-600">
            {typeLabel}
          </span>
          {meta ? <span className="truncate text-foreground-secondary text-xs">{meta}</span> : null}
        </div>
        {sim ? (
          <span className="shrink-0 font-mono text-[11px] text-foreground-tertiary">sim {sim}</span>
        ) : null}
      </div>

      <div className="relative overflow-hidden rounded-xl border border-border">
        {url ? (
          <button type="button" onClick={open} className="block w-full" aria-label={t("zoom")}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={url}
              alt={`#${item.index}`}
              loading="lazy"
              className={
                isExpanded
                  ? "max-h-[min(60vh,520px)] w-full object-contain"
                  : "h-56 w-full object-cover"
              }
            />
          </button>
        ) : (
          <div className="grid h-56 w-full place-items-center bg-background-secondary text-foreground-tertiary text-sm">
            {imageId || `#${item.index}`}
          </div>
        )}
        {url ? (
          <button
            type="button"
            onClick={open}
            className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-lg bg-black/55 px-2 py-1 font-medium text-[11px] text-white backdrop-blur-sm transition-colors hover:bg-black/70"
          >
            <Maximize2 size={12} strokeWidth={2.2} aria-hidden />
            {t("zoom")}
          </button>
        ) : null}
      </div>

      {contentSummary ? (
        <MarkdownSnippet
          lineClamp={isExpanded ? undefined : 3}
          className={`mt-2.5 ${isExpanded ? "text-[14px]" : "text-[13px]"}`}
        >
          {contentSummary}
        </MarkdownSnippet>
      ) : (
        <div className="mt-2.5 flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-[11px] text-foreground-tertiary">
            {t("visualCaption")}
          </p>
          <span className="inline-flex shrink-0 items-center rounded-md bg-violet-100 px-2 py-0.5 font-mono text-[10px] font-medium text-violet-600">
            {t("eagleVisual")}
          </span>
        </div>
      )}

      {parentSection ? (
        <button
          type="button"
          onClick={() => documentId && onViewStructure(documentId, parentSection)}
          disabled={!documentId}
          className="mt-2 flex w-full items-center gap-1.5 truncate rounded-lg bg-(--surface-muted) px-2 py-1 text-left font-mono text-[11px] text-foreground-secondary transition-colors hover:text-accent disabled:hover:text-foreground-secondary"
          title={parentSection}
        >
          <ListTree size={12} strokeWidth={2} className="shrink-0" aria-hidden />
          <span className="truncate">{parentSection}</span>
        </button>
      ) : null}

      {sourceChunkId ? (
        <p
          className="mt-2 truncate font-mono text-[10.5px] text-foreground-tertiary"
          title={sourceChunkId}
        >
          {t("sourceChunk")}: {sourceChunkId}
        </p>
      ) : null}

      {documentId && chunkType === "table" && sourceChunkId ? (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() =>
              onPreview({
                kind: "table",
                documentId,
                chunkId: sourceChunkId,
                title: parentSection || typeLabel,
              })
            }
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 font-medium text-[11px] text-foreground-secondary transition-colors hover:bg-background-secondary"
          >
            <Sheet size={12} strokeWidth={2} aria-hidden />
            {t("previewTable")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
