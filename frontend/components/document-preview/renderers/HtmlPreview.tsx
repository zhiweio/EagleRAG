"use client";

import {
  WebPreview,
  WebPreviewBody,
  WebPreviewNavigation,
  WebPreviewUrl,
} from "@/components/ai-elements/web-preview";
import { viewerChromeClass } from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

interface HtmlPreviewProps {
  title: string;
  layout: PreviewLayout;
  /** blob: URL or remote same-origin file URL for uploaded HTML. */
  src?: string;
  blob?: Blob;
  /** Live http(s) source URI for URL-ingested corpus (no blob fetch). */
  externalUrl?: string;
}

async function readHtmlText(src: string | undefined, blob: Blob | undefined): Promise<string> {
  if (blob) return blob.text();
  if (!src) throw new Error("HTML source missing");
  const response = await fetch(src);
  if (!response.ok) throw new Error(String(response.status));
  return response.text();
}

/** HTML / web-page preview: srcDoc for uploads, live iframe for URL corpus. */
export function HtmlPreview({ title, layout, src, blob, externalUrl }: HtmlPreviewProps) {
  if (externalUrl) {
    return (
      <ExternalHtmlPreview
        key={externalUrl}
        title={title}
        layout={layout}
        externalUrl={externalUrl}
      />
    );
  }

  return <UploadedHtmlPreview title={title} layout={layout} src={src} blob={blob} />;
}

function UploadedHtmlPreview({
  title,
  layout,
  src,
  blob,
}: {
  title: string;
  layout: PreviewLayout;
  src?: string;
  blob?: Blob;
}) {
  const t = useTranslations("documentPreview");
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setError(false);

    readHtmlText(src, blob)
      .then((value) => {
        if (!cancelled) setHtml(value);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [src, blob]);

  if (error) {
    return <p className="py-6 text-center text-foreground-tertiary text-xs">{t("error")}</p>;
  }

  if (html === null) {
    return (
      <div className="flex h-full min-h-32 items-center justify-center">
        <Spinner className="size-5" />
        <span className="sr-only">{t("loading")}</span>
      </div>
    );
  }

  return (
    <WebPreview className={viewerChromeClass(layout)}>
      <WebPreviewNavigation>
        <WebPreviewUrl value={title} href={src} />
      </WebPreviewNavigation>
      <WebPreviewBody srcDoc={html} title={title} />
    </WebPreview>
  );
}

function ExternalHtmlPreview({
  title,
  layout,
  externalUrl,
}: {
  title: string;
  layout: PreviewLayout;
  externalUrl: string;
}) {
  const t = useTranslations("documentPreview");
  const [blocked, setBlocked] = useState(false);

  if (blocked) {
    return (
      <WebPreview className={viewerChromeClass(layout)}>
        <WebPreviewNavigation>
          <WebPreviewUrl value={externalUrl} href={externalUrl} />
        </WebPreviewNavigation>
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 bg-surface px-6 text-center">
          <p className="max-w-sm text-foreground-secondary text-xs leading-relaxed">
            {t("frameBlocked")}
          </p>
          <Button asChild size="sm" variant="secondary">
            <a href={externalUrl} rel="noreferrer" target="_blank">
              <ExternalLink className="size-3.5" aria-hidden />
              {t("openNewTab")}
            </a>
          </Button>
        </div>
      </WebPreview>
    );
  }

  return (
    <WebPreview className={viewerChromeClass(layout)}>
      <WebPreviewNavigation>
        <WebPreviewUrl value={externalUrl} href={externalUrl} />
      </WebPreviewNavigation>
      <WebPreviewBody src={externalUrl} title={title} onError={() => setBlocked(true)} />
    </WebPreview>
  );
}
