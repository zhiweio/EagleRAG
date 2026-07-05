"use client";

import { PIPELINE_STYLES } from "@/components/kb/kb-visuals";
import type { PipelineKind } from "@/lib/kb/types";
import { useTranslations } from "next-intl";

function toKind(pipeline: string | null | undefined): PipelineKind | null {
  const p = (pipeline ?? "").toLowerCase();
  if (p.includes("pixel") || p.includes("visual")) return "pixelrag";
  if (p.includes("know") || p.includes("text")) return "knowhere";
  return null;
}

/**
 * PipelineBadge — coloured tag for the processing pipeline.
 * Knowhere blue (text) / PixelRAG purple (visual), taken from the design frame palette.
 * Label is locale-aware; no icon is rendered (keeps the column compact and avoids
 * duplicating the document icon).
 */
export function PipelineBadge({ pipeline }: { pipeline: string | null | undefined }) {
  const t = useTranslations("ingest.filters");
  const kind = toKind(pipeline);
  if (!kind) {
    return (
      <span className="inline-flex items-center rounded-md bg-(--surface-muted) px-2 py-1 text-xs font-medium text-foreground-secondary">
        {pipeline || "—"}
      </span>
    );
  }
  const style = PIPELINE_STYLES[kind];
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold whitespace-nowrap"
      style={{ backgroundColor: style.soft, color: style.color }}
    >
      {t(kind)}
    </span>
  );
}
