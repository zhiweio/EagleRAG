import type { IconTone } from "@/lib/health/types";
import type { CSSProperties } from "react";

/**
 * Shared visual tokens for the Service Health module. Most tones map onto the
 * theme's soft/foreground CSS variables; `purple` (used by PixelRAG and the
 * model engine) is not a theme token, so it is expressed as an inline style.
 */
export interface ToneStyle {
  className?: string;
  style?: CSSProperties;
}

/** Soft icon-box fill + glyph color per tone. */
export const ICON_TONE: Record<IconTone, ToneStyle> = {
  accent: { className: "bg-accent-soft text-accent-soft-foreground" },
  success: { className: "bg-success-soft text-success-soft-foreground" },
  warning: { className: "bg-warning-soft text-warning-soft-foreground" },
  danger: { className: "bg-danger-soft text-danger-soft-foreground" },
  purple: { style: { backgroundColor: "rgba(124,92,246,0.14)", color: "#7C5CF6" } },
};

/** Soft chip fill + text per metric-chip tone. */
export const CHIP_TONE: Record<"accent" | "success" | "warning", string> = {
  accent: "bg-accent-soft text-accent-soft-foreground",
  success: "bg-success-soft text-success-soft-foreground",
  warning: "bg-warning-soft text-warning-soft-foreground",
};

/** Status dot color per service status. */
export const STATUS_DOT: Record<"online" | "degraded" | "offline" | "unknown", string> = {
  online: "bg-success",
  degraded: "bg-warning",
  offline: "bg-danger",
  // Neutral gray: indicates "not probed / disabled" rather than failure, distinct from red offline.
  unknown: "bg-foreground-tertiary",
};
