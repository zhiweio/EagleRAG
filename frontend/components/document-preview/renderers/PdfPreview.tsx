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
  resourceKey?: string | null;
}

export function PdfPreview({ src, fileName, layout, resourceKey }: PdfPreviewProps) {
  const toolbar = viewerToolbarProps(layout);

  return (
    <PDFViewer
      key={resourceKey ?? fileName ?? src}
      className={viewerChromeClass(layout)}
      src={src}
      fileName={fileName}
      defaultZoom={viewerDefaultPdfZoom(layout)}
      {...toolbar}
    />
  );
}
