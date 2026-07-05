"use client";

import type { TaskPhase } from "@/components/ingest/status";
import { cn } from "@/components/ui";

const DOT_CLASS: Record<TaskPhase, string> = {
  pending: "bg-warning",
  running: "bg-accent",
  success: "bg-success",
  failed: "bg-danger",
};

const TEXT_CLASS: Record<TaskPhase, string> = {
  pending: "text-warning",
  running: "text-accent",
  success: "text-success",
  failed: "text-danger",
};

/**
 * StatusPill — status dot + uppercase bold status name (design frame State column style).
 * The status dot pulses when running.
 */
export function StatusPill({ phase, label }: { phase: TaskPhase; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs font-bold", TEXT_CLASS[phase])}>
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          DOT_CLASS[phase],
          phase === "running" && "animate-pulse",
        )}
      />
      {label}
    </span>
  );
}
