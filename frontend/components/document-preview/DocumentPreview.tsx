"use client";

import { DocumentPreviewShell } from "@/components/document-preview/DocumentPreviewShell";
import { previewContentUrl, previewTitle } from "@/components/document-preview/preview-urls";
import { CsvPreview } from "@/components/document-preview/renderers/CsvPreview";
import { DocxPreview } from "@/components/document-preview/renderers/DocxPreview";
import { FallbackPreview } from "@/components/document-preview/renderers/FallbackPreview";
import { HtmlTablePreview } from "@/components/document-preview/renderers/HtmlTablePreview";
import { ImagePreview } from "@/components/document-preview/renderers/ImagePreview";
import { PdfPreview } from "@/components/document-preview/renderers/PdfPreview";
import { XlsxPreview } from "@/components/document-preview/renderers/XlsxPreview";
import { resolveRenderer } from "@/components/document-preview/resolve-renderer";
import type { PreviewLayout, PreviewTarget } from "@/components/document-preview/types";
import { imageUrl } from "@/lib/api/client";
import { attachmentContentUrl } from "@/lib/hooks/useAttachments";
import { cn } from "@/lib/utils";
import { FileSearch } from "lucide-react";
import { useTranslations } from "next-intl";

export interface DocumentPreviewProps {
  target: PreviewTarget | null;
  layout?: PreviewLayout;
  className?: string;
  onZoom?: () => void;
}

/** Format-aware document preview dispatcher backed by Extend UI viewers. */
export function DocumentPreview({
  target,
  layout = "rail",
  className,
  onZoom,
}: DocumentPreviewProps) {
  const t = useTranslations("documentPreview");

  if (!target) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-separator bg-(--surface-muted)/30 px-6 py-10 text-center",
          className,
        )}
      >
        <span className="inline-flex size-10 items-center justify-center rounded-xl bg-(--surface-muted) text-foreground-tertiary">
          <FileSearch size={18} strokeWidth={1.75} aria-hidden />
        </span>
        <p className="max-w-[16rem] text-foreground-tertiary text-xs leading-relaxed">
          {t("empty")}
        </p>
      </div>
    );
  }

  const title = previewTitle(target);
  const href = previewContentUrl(target);
  const renderer = resolveRenderer(target);
  const showShell = layout !== "inline" && layout !== "modal";

  const body = renderBody(target, layout, renderer, onZoom);

  if (!showShell) {
    return <div className={cn("min-h-0", className)}>{body}</div>;
  }

  return (
    <div className={cn("min-h-0", className)}>
      <DocumentPreviewShell title={title} href={href} layout={layout} onZoom={onZoom}>
        {body}
      </DocumentPreviewShell>
    </div>
  );
}

function renderBody(
  target: PreviewTarget,
  layout: PreviewLayout,
  renderer: ReturnType<typeof resolveRenderer>,
  onZoom?: () => void,
) {
  const title = previewTitle(target);

  if (renderer === "image") {
    const src =
      target.kind === "image"
        ? imageUrl(target.imageId)
        : target.kind === "attachment"
          ? (target.previewUrl ?? attachmentContentUrl(target.attachmentId))
          : (previewContentUrl(target) ?? "");

    return <ImagePreview src={src} alt={title} layout={layout} onZoom={onZoom} />;
  }

  if (renderer === "table" && target.kind === "table") {
    return (
      <HtmlTablePreview
        title={title}
        layout={layout}
        html={target.html}
        remoteUrl={
          target.chunkId ? previewContentUrl({ ...target, kind: "table" as const }) : undefined
        }
      />
    );
  }

  const src = previewContentUrl(target);
  if (!src) {
    return null;
  }

  switch (renderer) {
    case "pdf":
      return <PdfPreview src={src} fileName={title} layout={layout} />;
    case "docx":
      return <DocxPreview src={src} fileName={title} layout={layout} />;
    case "xlsx":
      return <XlsxPreview src={src} fileName={title} layout={layout} />;
    case "csv":
      return <CsvPreview src={src} layout={layout} />;
    default:
      return <FallbackPreview src={src} title={title} layout={layout} />;
  }
}
