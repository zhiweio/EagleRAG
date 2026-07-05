"use client";

import { Sparkles } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** Strip trailing ellipsis so animated dots can replace them. */
function stripTrailingEllipsis(text: string): string {
  return text.replace(/[.…\s]+$/u, "").trimEnd();
}

export type ThinkingSparkleProps = ComponentProps<"span">;

/** Pulsing sparkle — Gemini-style “model is working” affordance. */
export function ThinkingSparkle({ className, ...props }: ThinkingSparkleProps) {
  return (
    <span
      aria-hidden
      className={cn("inline-flex size-4 shrink-0 items-center justify-center", className)}
      {...props}
    >
      <Sparkles className="thinking-sparkle size-4 text-accent" strokeWidth={2} />
    </span>
  );
}

export type ThinkingDotsProps = ComponentProps<"span">;

/** Three staggered dots (replaces static “…”). */
export function ThinkingDots({ className, ...props }: ThinkingDotsProps) {
  return (
    <span aria-hidden className={cn("inline-flex w-[0.9em] translate-y-px", className)} {...props}>
      {[0, 1, 2].map((i) => (
        <span
          className="thinking-dot text-accent"
          key={i}
          style={{ animationDelay: `${i * 0.18}s` }}
        >
          .
        </span>
      ))}
    </span>
  );
}

export type ThinkingShimmerTextProps = ComponentProps<"span"> & {
  /** When true, append animated dots after the label. */
  withDots?: boolean;
};

/** Iridescent gradient sweep across thinking copy (Gemini-like). */
export function ThinkingShimmerText({
  children,
  className,
  withDots = true,
  ...props
}: ThinkingShimmerTextProps) {
  const raw = typeof children === "string" ? children : String(children ?? "");
  const label = stripTrailingEllipsis(raw);

  return (
    <span className={cn("inline-flex items-baseline font-medium", className)} {...props}>
      <span className="thinking-shimmer">{label}</span>
      {withDots ? <ThinkingDots /> : null}
    </span>
  );
}

export type ThinkingLabelProps = ComponentProps<"span"> & {
  active?: boolean;
};

/** Header / placeholder row: sparkle + shimmer while active, plain text when done. */
export function ThinkingLabel({
  active = false,
  children,
  className,
  ...props
}: ThinkingLabelProps) {
  if (!active) {
    return (
      <span className={cn("text-foreground", className)} {...props}>
        {children}
      </span>
    );
  }

  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2", className)} {...props}>
      <ThinkingSparkle />
      <ThinkingShimmerText>{children}</ThinkingShimmerText>
    </span>
  );
}
