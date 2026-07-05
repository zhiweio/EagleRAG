import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

/**
 * Chip — soft, pill-shaped label used for status, counts and tags.
 * Design refs: Queue Chip (accent-soft, dot + text), status chips, AI Native chip.
 */
export type ChipTone = "accent" | "success" | "warning" | "danger" | "neutral";

const TONE_CLASS: Record<ChipTone, string> = {
  accent: "bg-accent-soft text-accent-soft-foreground",
  success: "bg-success-soft text-success-soft-foreground",
  warning: "bg-warning-soft text-warning-soft-foreground",
  danger: "bg-danger-soft text-danger-soft-foreground",
  neutral: "bg-background-secondary text-foreground-secondary",
};

const DOT_CLASS: Record<ChipTone, string> = {
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  neutral: "bg-foreground-tertiary",
};

export interface ChipProps {
  children: ReactNode;
  tone?: ChipTone;
  /** Show a leading status dot in the tone color. */
  dot?: boolean;
  /** Optional leading lucide icon. */
  icon?: LucideIcon;
  size?: "sm" | "md";
  className?: string;
}

export function Chip({
  children,
  tone = "neutral",
  dot,
  icon: Icon,
  size = "md",
  className,
}: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-semibold whitespace-nowrap",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-xs",
        TONE_CLASS[tone],
        className,
      )}
    >
      {dot ? (
        <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASS[tone])} />
      ) : null}
      {Icon ? <Icon size={size === "sm" ? 12 : 14} strokeWidth={2} aria-hidden /> : null}
      {children}
    </span>
  );
}

/**
 * OutlineChip — bordered, low-emphasis pill (e.g. "AI Native", format tags).
 */
export function OutlineChip({
  children,
  icon: Icon,
  className,
}: {
  children: ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-foreground-secondary whitespace-nowrap",
        className,
      )}
    >
      {Icon ? <Icon size={12} strokeWidth={2} aria-hidden /> : null}
      {children}
    </span>
  );
}
