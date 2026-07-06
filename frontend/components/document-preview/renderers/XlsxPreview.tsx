"use client";

import {
  viewerChromeClass,
  viewerDefaultZoomPercent,
  viewerToolbarProps,
} from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Spinner } from "@/components/ui/spinner";
import dynamic from "next/dynamic";
import { useState } from "react";

const XlsxViewerPreview = dynamic(
  () => import("@/components/ui/xlsx-viewer").then((m) => m.XlsxViewerPreview),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    ),
  },
);

interface XlsxPreviewProps {
  src: string;
  fileName?: string;
  layout: PreviewLayout;
}

export function XlsxPreview({ src, fileName, layout }: XlsxPreviewProps) {
  const toolbar = viewerToolbarProps(layout);
  const [isDark, setIsDark] = useState(false);

  return (
    <XlsxViewerPreview
      key={layout}
      className={viewerChromeClass(layout)}
      src={src}
      fileName={fileName}
      defaultZoom={viewerDefaultZoomPercent(layout)}
      isDark={isDark}
      onIsDarkChange={setIsDark}
      {...toolbar}
    />
  );
}
