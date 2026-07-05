"use client";

import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview";
import { chunkHtmlUrl, fileUrl, imageUrl } from "@/lib/api/client";
import { Download, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { PanelLayout, PreviewTarget } from "./types";

interface FilePreviewProps {
  target: PreviewTarget | null;
  layout?: PanelLayout;
  onImageClick: (imageId: string) => void;
}

/** Wrap raw table HTML in a minimal, light-themed document for the iframe. */
function tableDocument(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13px;color:#18181b;margin:0;padding:12px;background:#fff}
    table{border-collapse:collapse;width:100%;font-size:12px}
    th,td{border:1px solid #dedee0;padding:6px 8px;text-align:left;vertical-align:top}
    th{background:#f5f5f5;font-weight:600}
    img{max-width:100%}
  </style></head><body>${html}</body></html>`;
}

/**
 * FilePreview — the evidence rail's File Preview surface. Renders the selected
 * evidence inline: images (with a zoom-to-lightbox affordance), Knowhere table
 * chunks (rendered HTML), and original ingested files (PDF / HTML / images) via
 * a sandboxed iframe, with open-in-new and download affordances.
 */
export function FilePreview({ target, layout = "rail", onImageClick }: FilePreviewProps) {
  const t = useTranslations("qa.preview");
  const isExpanded = layout === "expanded";
  const previewHeight = isExpanded ? "h-[min(72vh,720px)]" : "h-[60vh]";
  const imageMaxHeight = isExpanded ? "max-h-[min(72vh,720px)]" : "max-h-[60vh]";

  if (!target) {
    return <p className="px-1 py-6 text-center text-foreground-tertiary text-xs">{t("empty")}</p>;
  }

  if (target.kind === "image") {
    const url = imageUrl(target.imageId);
    return (
      <div className="space-y-2">
        <div className="relative overflow-hidden rounded-xl border border-border bg-(--surface-muted)">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt={target.title ?? target.imageId}
            className={`${imageMaxHeight} w-full object-contain`}
          />
          <button
            type="button"
            onClick={() => onImageClick(target.imageId)}
            className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-lg bg-black/55 px-2 py-1 font-medium text-[11px] text-white backdrop-blur-sm transition-colors hover:bg-black/70"
          >
            <Maximize2 size={12} strokeWidth={2.2} aria-hidden />
            {t("zoom")}
          </button>
        </div>
        <PreviewFooter href={url} title={target.title ?? target.imageId} />
      </div>
    );
  }

  if (target.kind === "table") {
    const remoteUrl = target.chunkId ? chunkHtmlUrl(target.documentId, target.chunkId) : undefined;
    return (
      <WebPreview className={previewHeight}>
        <WebPreviewNavigation>
          <WebPreviewUrl value={target.title ?? t("table")} href={remoteUrl} />
        </WebPreviewNavigation>
        {target.html ? (
          <WebPreviewBody srcDoc={tableDocument(target.html)} title={target.title ?? "table"} />
        ) : remoteUrl ? (
          <WebPreviewBody src={remoteUrl} title={target.title ?? "table"} />
        ) : (
          <p className="p-4 text-foreground-tertiary text-xs">{t("empty")}</p>
        )}
      </WebPreview>
    );
  }

  // Original ingested file (PDF / HTML / image) — served inline or 307-redirected.
  const url = fileUrl(target.documentId);
  return (
    <WebPreview className={previewHeight}>
      <WebPreviewNavigation>
        <WebPreviewUrl value={target.title ?? target.documentId} href={url} />
      </WebPreviewNavigation>
      <WebPreviewBody src={url} title={target.title ?? "file"} />
    </WebPreview>
  );
}

function PreviewFooter({ href, title }: { href: string; title: string }) {
  const t = useTranslations("qa.preview");
  return (
    <a
      href={href}
      download={title}
      className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 font-medium text-[12px] text-foreground-secondary transition-colors hover:bg-(--surface-muted)"
    >
      <Download size={13} strokeWidth={2} aria-hidden />
      {t("download")}
    </a>
  );
}
