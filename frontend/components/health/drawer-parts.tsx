import { cn } from "@/components/ui";
import type { ReactNode } from "react";

/**
 * Shared presentational parts for the unified ServiceDrawer dashboards
 * (design frames 04–07, 12, 13). Kept intentionally small and prop-driven so
 * each per-service dashboard just composes them with mock data.
 */

/** Bordered section with a title row (+ optional trailing note) and body. */
export function DrawerPanel({
  title,
  note,
  children,
  bodyClassName,
}: {
  title: ReactNode;
  note?: ReactNode;
  children: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className="rounded-2xl border border-border bg-(--surface-muted)/40 p-4">
      <header className="mb-3 flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-foreground">{title}</h4>
        {note ? <span className="text-xs text-foreground-tertiary">{note}</span> : null}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** KPI tile: caption label, large value (optionally tinted), and a sub note. */
export function DrawerStatCard({
  label,
  value,
  sub,
  tone = "default",
  children,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "accent" | "success" | "danger";
  children?: ReactNode;
}) {
  const valueClass = {
    default: "text-foreground",
    accent: "text-accent",
    success: "text-success",
    danger: "text-danger",
  }[tone];

  return (
    <div className="flex flex-col gap-1.5 rounded-2xl border border-border bg-surface p-4">
      <span className="text-[11px] font-medium text-foreground-tertiary">{label}</span>
      <span className={cn("text-2xl font-semibold leading-none tabular-nums", valueClass)}>
        {value}
      </span>
      {children}
      {sub ? <span className="text-[11px] text-foreground-secondary">{sub}</span> : null}
    </div>
  );
}

/** Thin horizontal progress bar (used for memory / CPU usage). */
export function ProgressBar({
  percent,
  tone = "accent",
  className,
}: {
  percent: number;
  tone?: "accent" | "success" | "warning" | "danger";
  className?: string;
}) {
  const fill = {
    accent: "bg-accent",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
  }[tone];
  return (
    <span
      aria-hidden
      className={cn(
        "block h-1.5 w-full overflow-hidden rounded-full bg-(--surface-muted)",
        className,
      )}
    >
      <span
        className={cn("block h-full rounded-full", fill)}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </span>
  );
}

/** Labeled mono field box (Dim / Metric / Index), as seen in the accordions. */
export function FieldBox({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-border bg-surface px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-tertiary">
        {label}
      </span>
      <span className="font-mono text-sm font-semibold text-foreground">{value}</span>
    </div>
  );
}
