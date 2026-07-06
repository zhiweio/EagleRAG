"use client";

import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview";
import { viewerChromeClass } from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { useTranslations } from "next-intl";

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

interface HtmlTablePreviewProps {
  title: string;
  layout: PreviewLayout;
  html?: string;
  remoteUrl?: string;
}

export function HtmlTablePreview({ title, layout, html, remoteUrl }: HtmlTablePreviewProps) {
  const t = useTranslations("documentPreview");

  return (
    <WebPreview className={viewerChromeClass(layout)}>
      <WebPreviewNavigation>
        <WebPreviewUrl value={title || t("table")} href={remoteUrl} />
      </WebPreviewNavigation>
      {html ? (
        <WebPreviewBody srcDoc={tableDocument(html)} title={title || "table"} />
      ) : remoteUrl ? (
        <WebPreviewBody src={remoteUrl} title={title || "table"} />
      ) : (
        <p className="p-4 text-foreground-tertiary text-xs">{t("empty")}</p>
      )}
    </WebPreview>
  );
}
