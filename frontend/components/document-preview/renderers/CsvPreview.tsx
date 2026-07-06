"use client";

import {
  viewerChromeClass,
  viewerDefaultZoomPercent,
} from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Spinner } from "@/components/ui/spinner";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const CsvViewer = dynamic(() => import("@/components/ui/csv-viewer").then((m) => m.CsvViewer), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center">
      <Spinner />
    </div>
  ),
});

interface CsvPreviewProps {
  src: string;
  layout: PreviewLayout;
}

export function CsvPreview({ src, layout }: CsvPreviewProps) {
  const t = useTranslations("documentPreview");
  const [data, setData] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);

    fetch(src)
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setData(text);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [src]);

  if (error) {
    return <p className="py-6 text-center text-foreground-tertiary text-xs">{t("error")}</p>;
  }

  if (!data) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <CsvViewer
      key={layout}
      className={viewerChromeClass(layout)}
      data={data}
      search={layout === "modal"}
      defaultZoomPercent={viewerDefaultZoomPercent(layout)}
    />
  );
}
