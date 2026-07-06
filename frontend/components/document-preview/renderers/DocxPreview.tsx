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

const DocxViewerPreview = dynamic(
  () => import("@/components/ui/docx-viewer").then((m) => m.DocxViewerPreview),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    ),
  },
);

interface DocxPreviewProps {
  src: string;
  fileName?: string;
  layout: PreviewLayout;
}

export function DocxPreview({ src, fileName, layout }: DocxPreviewProps) {
  const toolbar = viewerToolbarProps(layout);
  const [isDark, setIsDark] = useState(false);

  return (
    <DocxViewerPreview
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
