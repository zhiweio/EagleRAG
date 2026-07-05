"use client";

import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

/**
 * IconButton — 36×36 circular ghost button used in the app bar (bell, settings,
 * history) and drawer/card controls.
 */
export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  label: string;
  size?: number;
  iconSize?: number;
  /** Optional badge count (e.g. unread notifications). */
  badge?: number;
}

export function IconButton({
  icon: Icon,
  label,
  size = 36,
  iconSize = 18,
  badge,
  className,
  type: _type,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn(
        "relative inline-flex items-center justify-center rounded-full text-foreground-secondary transition-colors hover:bg-background-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1",
        className,
      )}
      style={{ width: size, height: size }}
      {...rest}
    >
      <Icon size={iconSize} strokeWidth={2} aria-hidden />
      {badge && badge > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-danger-foreground">
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </button>
  );
}
