"use client";

import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview";
import { viewerChromeClass } from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";

interface FallbackPreviewProps {
  src: string;
  title: string;
  layout: PreviewLayout;
}

/** Generic iframe fallback for formats without a dedicated extend viewer. */
export function FallbackPreview({ src, title, layout }: FallbackPreviewProps) {
  return (
    <WebPreview className={viewerChromeClass(layout)}>
      <WebPreviewNavigation>
        <WebPreviewUrl value={title} href={src} />
      </WebPreviewNavigation>
      <WebPreviewBody src={src} title={title} />
    </WebPreview>
  );
}
