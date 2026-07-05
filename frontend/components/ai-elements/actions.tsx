"use client";

import type { ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ActionsProps = ComponentProps<"div">;

/** A horizontal row of icon actions rendered under an assistant message. */
export function Actions({ className, children, ...props }: ActionsProps) {
  return (
    <div className={cn("flex items-center gap-1", className)} {...props}>
      {children}
    </div>
  );
}

export type ActionProps = ComponentProps<typeof Button> & {
  tooltip?: string;
  label?: string;
};

export function Action({
  tooltip,
  children,
  label,
  className,
  size = "icon",
  variant = "ghost",
  ...props
}: ActionProps) {
  return (
    <Button
      aria-label={label || tooltip}
      className={cn("relative size-8 text-muted-foreground hover:text-foreground", className)}
      size={size}
      title={tooltip}
      type="button"
      variant={variant}
      {...props}
    >
      {children}
      <span className="sr-only">{label || tooltip}</span>
    </Button>
  );
}
