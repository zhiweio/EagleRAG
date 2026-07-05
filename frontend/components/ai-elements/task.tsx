"use client";

import { ChevronDownIcon, SearchIcon } from "lucide-react";
import { Collapsible } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type TaskProps = ComponentProps<typeof Collapsible.Root>;

/** A collapsible task block used to group a retrieval sub-step's file hits. */
export function Task({ className, defaultOpen = false, ...props }: TaskProps) {
  return (
    <Collapsible.Root className={cn("w-full", className)} defaultOpen={defaultOpen} {...props} />
  );
}

export type TaskTriggerProps = ComponentProps<typeof Collapsible.Trigger> & {
  title: string;
};

export function TaskTrigger({ children, className, title, ...props }: TaskTriggerProps) {
  return (
    <Collapsible.Trigger
      className={cn("group flex w-full items-center gap-2 text-muted-foreground", className)}
      {...props}
    >
      {children ?? (
        <>
          <SearchIcon className="size-3.5" />
          <span className="text-xs">{title}</span>
          <ChevronDownIcon className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </>
      )}
    </Collapsible.Trigger>
  );
}

export type TaskContentProps = ComponentProps<typeof Collapsible.Content>;

export function TaskContent({ children, className, ...props }: TaskContentProps) {
  return (
    <Collapsible.Content
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className,
      )}
      {...props}
    >
      <div className="mt-1.5 space-y-1 border-border border-l pl-4">{children}</div>
    </Collapsible.Content>
  );
}

export type TaskItemProps = ComponentProps<"div">;

export function TaskItem({ children, className, ...props }: TaskItemProps) {
  return (
    <div className={cn("text-muted-foreground text-xs", className)} {...props}>
      {children}
    </div>
  );
}

export type TaskItemFileProps = ComponentProps<"span">;

export function TaskItemFile({ children, className, ...props }: TaskItemFileProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[10.5px] text-foreground",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}
