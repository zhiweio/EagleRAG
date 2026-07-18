"use client";

import { CodeBlock } from "@/components/ai-elements/code-block";
import { Response } from "@/components/ai-elements/response";
import { viewerChromeClass } from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

interface MarkdownPreviewProps {
  src?: string;
  blob?: Blob;
  layout: PreviewLayout;
}

type MarkdownMode = "preview" | "markdown";

async function readMarkdownText(src: string | undefined, blob: Blob | undefined): Promise<string> {
  if (blob) return blob.text();
  if (!src) throw new Error("Markdown source missing");
  const response = await fetch(src);
  if (!response.ok) throw new Error(String(response.status));
  return response.text();
}

/** Document Markdown viewer with rendered Preview vs raw Markdown source. */
export function MarkdownPreview({ src, blob, layout }: MarkdownPreviewProps) {
  const t = useTranslations("documentPreview");
  const [mode, setMode] = useState<MarkdownMode>("preview");
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setError(false);

    readMarkdownText(src, blob)
      .then((value) => {
        if (!cancelled) setText(value);
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

  if (text === null) {
    return (
      <div className="flex h-full min-h-32 items-center justify-center">
        <Spinner className="size-5" />
        <span className="sr-only">{t("loading")}</span>
      </div>
    );
  }

  return (
    <Tabs
      value={mode}
      onValueChange={(value) => setMode(value as MarkdownMode)}
      className={cn(viewerChromeClass(layout), "gap-0")}
    >
      <div className="flex shrink-0 items-center border-border border-b bg-secondary/40 px-2 py-1.5">
        <TabsList variant="default" className="h-7 p-0.5">
          <TabsTrigger value="preview" className="h-6 px-2.5 text-[11px]">
            {t("modePreview")}
          </TabsTrigger>
          <TabsTrigger value="markdown" className="h-6 px-2.5 text-[11px]">
            {t("modeMarkdown")}
          </TabsTrigger>
        </TabsList>
      </div>

      <TabsContent
        value="preview"
        className="min-h-0 flex-1 overflow-auto px-4 py-3 data-[state=inactive]:hidden"
      >
        <Response mode="static" className="max-w-none text-[13px] leading-relaxed">
          {text}
        </Response>
      </TabsContent>

      <TabsContent
        value="markdown"
        className="min-h-0 flex-1 overflow-hidden p-2 data-[state=inactive]:hidden"
      >
        <CodeBlock
          code={text}
          language="markdown"
          className="flex h-full min-h-0 flex-col border-0 bg-transparent [&_pre]:h-full [&_pre]:min-h-0 [&_pre]:overflow-auto"
        />
      </TabsContent>
    </Tabs>
  );
}
