"use client";

import type { LucideIcon } from "lucide-react";

export interface QueuePalette {
  /** Primary color (icon, worker subtitle, filled dots). */
  color: string;
  /** Card surface color. */
  surface: string;
  /** Status pill background color. */
  pillBg: string;
  /** Number highlight color (concurrency value). */
  accent: string;
}

export const QUEUE_GREEN: QueuePalette = {
  color: "#16a34a",
  surface: "#dcf5e6",
  pillBg: "#c4edd3",
  accent: "#16a34a",
};

export const QUEUE_PURPLE: QueuePalette = {
  color: "#7c3aed",
  surface: "#f3eefb",
  pillBg: "#e6dcf7",
  accent: "#7c3aed",
};

interface QueueCardProps {
  icon: LucideIcon;
  palette: QueuePalette;
  title: string;
  worker: string;
  pillLabel: string;
  footer: string;
  /** Concurrency indicator dots: total count and filled count. */
  dots: { total: number; filled: number };
}

/**
 * QueueCard — ingest queue card (text parsing / visual rendering).
 * Design: tinted surface + striped tile icon + title/worker + status pill + bottom concurrency dot grid.
 * Queue theme colors (green/purple) are not global tokens, so they are applied via inline styles.
 */
export function QueueCard({
  icon: Icon,
  palette,
  title,
  worker,
  pillLabel,
  footer,
  dots,
}: QueueCardProps) {
  return (
    <div
      className="flex flex-1 flex-col justify-between gap-4 rounded-xl p-4"
      style={{ backgroundColor: palette.surface }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
            style={{
              color: palette.color,
              backgroundImage: `repeating-linear-gradient(45deg, ${palette.color}2e 0, ${palette.color}2e 2px, transparent 2px, transparent 6px)`,
              boxShadow: `inset 0 0 0 1px ${palette.color}40`,
            }}
          >
            <Icon size={18} strokeWidth={2.2} />
          </span>
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold text-foreground">{title}</span>
            <span className="text-xs font-medium" style={{ color: palette.color }}>
              {worker}
            </span>
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
          style={{ backgroundColor: palette.pillBg, color: palette.color }}
        >
          <span
            aria-hidden
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: palette.color }}
          />
          {pillLabel}
        </span>
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-foreground-secondary">{footer}</span>
        <div className="flex items-center gap-1">
          {Array.from({ length: dots.total }, (_, i) => {
            const filled = i < dots.filled;
            return (
              <span
                // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length decorative dot grid
                key={i}
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={
                  filled
                    ? { backgroundColor: palette.color }
                    : { boxShadow: `inset 0 0 0 1px ${palette.color}59` }
                }
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
