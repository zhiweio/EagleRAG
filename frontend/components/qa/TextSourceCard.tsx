"use client";

import { FileText, ListTree, Sheet, Table2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { MarkdownSnippet } from "./MarkdownSnippet";
import {
  formatSim,
  sourceChunkType,
  sourceCrumbs,
  sourceDocumentId,
  sourceExcerpt,
  sourceFileName,
  sourceKeywords,
  sourcePageLabel,
  sourceString,
} from "./sources-utils";
import type { FlatSource, PanelLayout, PreviewTarget } from "./types";

interface TextSourceCardProps {
  item: FlatSource;
  highlighted: boolean;
  layout?: PanelLayout;
  registerRef: (index: number, el: HTMLDivElement | null) => void;
  onViewStructure: (documentId: string, path?: string) => void;
  onPreview: (target: PreviewTarget) => void;
}

/**
 * TextSourceCard — a Knowhere text/table/section chunk with full provenance:
 * chunk-type badge, section breadcrumb, page range, the chunk body excerpt,
 * keyword tags and relevance score, plus actions to jump into the document's
 * semantic tree or preview the underlying file/table.
 */
export function TextSourceCard({
  item,
  highlighted,
  layout = "rail",
  registerRef,
  onViewStructure,
  onPreview,
}: TextSourceCardProps) {
  const isExpanded = layout === "expanded";
  const t = useTranslations("qa.sources");
  const isAttachment = sourceString(item.source, "source") === "attachment";
  const chunkType = sourceChunkType(item.source);
  const isTable = chunkType === "table";
  const isSection = chunkType === "section_summary";
  const fileName = sourceFileName(item.source) || `#${item.index}`;
  const crumbs = sourceCrumbs(item.source);
  const excerpt = sourceExcerpt(item.source);
  const summary = sourceString(item.source, "summary");
  const keywords = sourceKeywords(item.source);
  const pageLabel = sourcePageLabel(item.source);
  const sim = formatSim(item.source);
  const documentId = sourceDocumentId(item.source);
  const chunkId = sourceString(item.source, "source_chunk_id") || sourceString(item.source, "id");

  const typeLabel = isAttachment
    ? t("attachment")
    : isSection
      ? t("sectionSummary")
      : isTable
        ? t("tableChunk")
        : t("knowhereGraph");
  const TypeIcon = isSection ? ListTree : isTable ? Table2 : FileText;

  return (
    <div
      ref={(el) => registerRef(item.index, el)}
      className={`rounded-2xl border bg-(--surface-muted) transition-all duration-300 ${
        isExpanded ? "p-4" : "p-3"
      } ${
        highlighted
          ? "border-accent ring-2 ring-accent-soft"
          : "border-border/60 hover:border-border"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft px-1 font-mono text-[10px] text-accent-soft-foreground">
          {item.index}
        </span>
        <TypeIcon size={14} strokeWidth={2} className="shrink-0 text-accent" aria-hidden />
        <button
          type="button"
          onClick={() =>
            documentId && onViewStructure(documentId, sourceString(item.source, "path"))
          }
          disabled={!documentId}
          className="min-w-0 flex-1 truncate text-left font-medium text-[13px] text-accent hover:underline disabled:no-underline"
          title={fileName}
        >
          {fileName}
        </button>
        <span className="inline-flex shrink-0 items-center rounded-md bg-blue-100 px-2 py-0.5 font-medium text-[11px] text-accent">
          {typeLabel}
        </span>
      </div>

      {crumbs.length > 0 ? (
        <p
          className={`mt-1.5 font-mono text-[11px] text-foreground-tertiary ${
            isExpanded ? "whitespace-pre-wrap break-words" : "truncate"
          }`}
          title={crumbs.join(" › ")}
        >
          {crumbs.join(" › ")}
        </p>
      ) : null}

      {excerpt ? (
        <MarkdownSnippet
          lineClamp={isExpanded ? undefined : 4}
          className={`mt-2 ${isExpanded ? "text-[14px]" : "text-[13px]"}`}
        >
          {excerpt}
        </MarkdownSnippet>
      ) : null}

      {summary && summary !== excerpt ? (
        <MarkdownSnippet
          lineClamp={isExpanded ? undefined : 2}
          className={`mt-2 border-accent/30 border-l-2 pl-2 text-foreground-tertiary italic ${
            isExpanded ? "text-[13px]" : "text-[12px]"
          }`}
        >
          {summary}
        </MarkdownSnippet>
      ) : null}

      {keywords.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {keywords.slice(0, 8).map((kw) => (
            <span
              key={kw}
              className="inline-flex items-center rounded bg-surface px-1.5 py-0.5 text-[10.5px] text-foreground-secondary"
            >
              {kw}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-2.5 flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 font-mono text-[11px] text-foreground-tertiary">
          {pageLabel ? <span>{pageLabel}</span> : null}
          {sim ? <span>sim {sim}</span> : null}
        </div>
        {documentId ? (
          <>
            {isTable ? (
              <button
                type="button"
                onClick={() =>
                  onPreview({
                    kind: "table",
                    documentId,
                    chunkId: chunkId || undefined,
                    html: excerpt || undefined,
                    title: fileName,
                  })
                }
                className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 font-medium text-[11px] text-foreground-secondary transition-colors hover:bg-background-secondary"
              >
                <Sheet size={12} strokeWidth={2} aria-hidden />
                {t("previewTable")}
              </button>
            ) : (
              <button
                type="button"
                onClick={() =>
                  onPreview({
                    kind: "file",
                    documentId,
                    title: fileName,
                    sourceType: sourceString(item.source, "source_type") || null,
                  })
                }
                className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 font-medium text-[11px] text-foreground-secondary transition-colors hover:bg-background-secondary"
              >
                <FileText size={12} strokeWidth={2} aria-hidden />
                {t("previewFile")}
              </button>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
