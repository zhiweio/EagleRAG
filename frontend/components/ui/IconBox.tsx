import type { LucideIcon } from "lucide-react";
import { cn } from "./cn";

/**
 * IconBox — the rounded, filled icon container used throughout the design
 * (logo mark, KB icon box, service icons, metric icons).
 *
 * Design refs: Logo 30×30 accent r9; KB Icon Box 28×28 accent-soft r8.
 */
type IconBoxVariant = "accent" | "accent-soft" | "surface" | "success" | "warning" | "danger";

const VARIANT_CLASS: Record<IconBoxVariant, string> = {
  accent: "bg-accent text-accent-foreground",
  "accent-soft": "bg-accent-soft text-accent-soft-foreground",
  surface: "bg-surface text-foreground-secondary border border-border",
  success: "bg-success-soft text-success-soft-foreground",
  warning: "bg-warning-soft text-warning-soft-foreground",
  danger: "bg-danger-soft text-danger-soft-foreground",
};

export interface IconBoxProps {
  icon: LucideIcon;
  variant?: IconBoxVariant;
  /** Box edge length in px. */
  size?: number;
  /** Icon glyph size in px. */
  iconSize?: number;
  /** Corner radius token. */
  radius?: "lg" | "xl" | "2xl" | "full";
  className?: string;
}

const RADIUS_CLASS = {
  lg: "rounded-lg",
  xl: "rounded-xl",
  "2xl": "rounded-2xl",
  full: "rounded-full",
} as const;

export function IconBox({
  icon: Icon,
  variant = "accent-soft",
  size = 28,
  iconSize = 16,
  radius = "lg",
  className,
}: IconBoxProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center",
        VARIANT_CLASS[variant],
        RADIUS_CLASS[radius],
        className,
      )}
      style={{ width: size, height: size }}
    >
      <Icon size={iconSize} strokeWidth={2} />
    </span>
  );
}
