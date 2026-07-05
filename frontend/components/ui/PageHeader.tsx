import type { ReactNode } from "react";
import { cn } from "./cn";

/**
 * PageHeader — the title block at the top of each page's content area.
 * Design ref (frame 02): 24/600 title + 14 secondary subtitle on the left,
 * action controls aligned to the baseline on the right.
 */
export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, actions, className }: PageHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {subtitle ? (
          <p className="max-w-2xl text-sm text-foreground-secondary">{subtitle}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2.5">{actions}</div> : null}
    </div>
  );
}
