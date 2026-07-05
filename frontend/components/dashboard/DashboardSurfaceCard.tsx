"use client";

import { Card, IconBox, type IconBoxProps, cn } from "@/components/ui";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface DashboardSurfaceCardProps {
  title: string;
  icon: LucideIcon;
  iconVariant?: IconBoxProps["variant"];
  action?: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

/** Shared dashboard module chrome — Card header row + content slot. */
export function DashboardSurfaceCard({
  title,
  icon: Icon,
  iconVariant = "accent-soft",
  action,
  badge,
  children,
  className,
  bodyClassName,
}: DashboardSurfaceCardProps) {
  return (
    <Card flush className={cn("flex h-full flex-col", className)}>
      <header className="flex items-center justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <IconBox icon={Icon} variant={iconVariant} size={40} iconSize={20} radius="xl" />
          <h2 className="truncate text-base font-semibold text-foreground">{title}</h2>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {badge}
          {action}
        </div>
      </header>
      <div className={cn("flex flex-1 flex-col gap-4 p-5", bodyClassName)}>{children}</div>
    </Card>
  );
}
