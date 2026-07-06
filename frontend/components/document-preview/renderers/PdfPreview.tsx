"use client";

import {
  viewerChromeClass,
  viewerDefaultPdfZoom,
  viewerToolbarProps,
} from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Spinner } from "@/components/ui/spinner";
import dynamic from "next/dynamic";

const PDFViewer = dynamic(() => import("@/components/ui/pdf-viewer").then((m) => m.PDFViewer), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center">
      <Spinner />
    </div>
  ),
});

interface PdfPreviewProps {
  src: string;
  fileName?: string;
  layout: PreviewLayout;
}

export function PdfPreview({ src, fileName, layout }: PdfPreviewProps) {
  const toolbar = viewerToolbarProps(layout);

  return (
    <PDFViewer
      key={layout}
      className={viewerChromeClass(layout)}
      src={src}
      fileName={fileName}
      defaultZoom={viewerDefaultPdfZoom(layout)}
      {...toolbar}
    />
  );
}
