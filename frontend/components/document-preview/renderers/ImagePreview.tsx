"use client";

import { previewImageMaxClass } from "@/components/document-preview/layout-utils";
import type { PreviewLayout } from "@/components/document-preview/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";

interface ImagePreviewProps {
  src: string;
  alt: string;
  layout: PreviewLayout;
  onZoom?: () => void;
}

export function ImagePreview({ src, alt, layout, onZoom }: ImagePreviewProps) {
  const t = useTranslations("documentPreview");
  const isInline = layout === "inline";
  const canZoom = Boolean(onZoom);

  const openZoom = () => onZoom?.();

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-lg border border-separator/70 bg-(--surface-muted)/50",
        canZoom && isInline && "cursor-zoom-in",
      )}
      onClick={canZoom && isInline ? openZoom : undefined}
      onKeyDown={
        canZoom && isInline
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openZoom();
              }
            }
          : undefined
      }
      role={canZoom && isInline ? "button" : undefined}
      tabIndex={canZoom && isInline ? 0 : undefined}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className={cn("w-full object-contain", previewImageMaxClass(layout))}
      />
      {layout !== "modal" && canZoom ? (
        <Button
          type="button"
          size="xs"
          variant="secondary"
          onClick={(e) => {
            e.stopPropagation();
            openZoom();
          }}
          className="absolute top-2 right-2 h-7 gap-1 border border-border/60 bg-surface/90 px-2 text-[11px] shadow-sm backdrop-blur-sm"
        >
          <Maximize2 size={12} strokeWidth={2.2} aria-hidden />
          {t("zoom")}
        </Button>
      ) : null}
    </div>
  );
}
