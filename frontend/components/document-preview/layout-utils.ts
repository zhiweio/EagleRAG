import type { PreviewLayout } from "@/components/document-preview/types";
import { cn } from "@/lib/utils";

export function previewHeightClass(layout: PreviewLayout): string {
  switch (layout) {
    case "inline":
      return "h-48 min-h-[12rem]";
    case "rail":
    case "panel":
    case "modal":
      return "h-full min-h-0";
    default:
      return "h-full min-h-0";
  }
}

export function previewImageMaxClass(layout: PreviewLayout): string {
  switch (layout) {
    case "inline":
      return "max-h-44";
    case "rail":
    case "panel":
      return "h-full max-h-full min-h-0";
    case "modal":
      return "max-h-[min(78vh,820px)]";
    default:
      return "h-full max-h-full min-h-0";
  }
}

export function viewerChromeClass(layout: PreviewLayout): string {
  return cn("flex min-h-0 w-full flex-col overflow-hidden", previewHeightClass(layout));
}

/** Extend viewers: hide upload everywhere; compact toolbar in rail/inline. */
export function viewerToolbarProps(layout: PreviewLayout) {
  const compact = layout === "inline" || layout === "rail";
  const fileActionsInChrome = layout === "modal" || layout === "panel";

  return {
    showUpload: false,
    showToolbar: true,
    showDownload: !compact && !fileActionsInChrome,
    showRotateControls: !compact,
    compactToolbar:
      layout === "rail" || layout === "inline" || layout === "modal" || layout === "panel",
  };
}

/** Default zoom for Extend viewers: compact rail preview vs expanded reading. */
export function viewerDefaultZoomPercent(layout: PreviewLayout): number {
  return layout === "rail" || layout === "inline" ? 50 : 100;
}

/** PDF embed plugin uses a 0–1 scale; docx/xlsx use whole-number percents. */
export function viewerDefaultPdfZoom(layout: PreviewLayout): number {
  return viewerDefaultZoomPercent(layout) / 100;
}
