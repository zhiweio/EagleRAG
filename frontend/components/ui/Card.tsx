import type { ReactNode } from "react";
import { cn } from "./cn";

/**
 * Card — the surface panel used for every content block in the design
 * (chat card, sources card, upload control, KPI cards, drawers, tables).
 *
 * Design ref: surface #FFF, border #DEDEE0, radius 2xl(16), shadow #0000000A.
 */
export interface CardProps {
  children: ReactNode;
  className?: string;
  /** Removes default padding so headers/rows can control their own spacing. */
  flush?: boolean;
}

export function Card({ children, className, flush }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-surface shadow-[0_1px_3px_0_rgba(0,0,0,0.04)]",
        !flush && "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * CardHeader — title row with optional subtitle and trailing actions.
 */
export interface CardHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, actions, icon, className }: CardHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-3", className)}>
      <div className="flex items-start gap-3">
        {icon}
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-foreground">{title}</span>
          {subtitle ? <span className="text-xs text-foreground-secondary">{subtitle}</span> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
