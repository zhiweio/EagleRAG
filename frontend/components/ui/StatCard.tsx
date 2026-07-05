import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { IconBox } from "./IconBox";
import { cn } from "./cn";

/**
 * StatCard — KPI / metric tile. Design ref: KPI Strip (label caption + large
 * value + optional icon box + optional delta).
 */
export interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  icon?: LucideIcon;
  iconVariant?: "accent" | "accent-soft" | "success" | "warning" | "danger";
  /** Small trailing note under/next to the value (e.g. "+12% this week"). */
  hint?: ReactNode;
  className?: string;
}

export function StatCard({
  label,
  value,
  icon,
  iconVariant = "accent-soft",
  hint,
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-2xl border border-border bg-surface p-4 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)]",
        className,
      )}
    >
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-foreground-tertiary">{label}</span>
        <span className="text-2xl font-semibold leading-none text-foreground tabular-nums">
          {value}
        </span>
        {hint ? <span className="text-[11px] text-foreground-secondary">{hint}</span> : null}
      </div>
      {icon ? (
        <IconBox icon={icon} variant={iconVariant} size={40} iconSize={20} radius="xl" />
      ) : null}
    </div>
  );
}
