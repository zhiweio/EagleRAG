"use client";

import { BookIcon, ChevronDownIcon } from "lucide-react";
import { Collapsible } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type SourcesProps = ComponentProps<typeof Collapsible.Root>;

/** A collapsible list of retrieval sources shown under an assistant answer. */
export function Sources({ className, ...props }: SourcesProps) {
  return <Collapsible.Root className={cn("not-prose text-xs", className)} {...props} />;
}

export type SourcesTriggerProps = ComponentProps<typeof Collapsible.Trigger> & {
  count: number;
  label?: string;
};

export function SourcesTrigger({
  className,
  count,
  label = "sources",
  children,
  ...props
}: SourcesTriggerProps) {
  return (
    <Collapsible.Trigger
      className={cn(
        "group flex items-center gap-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground",
        className,
      )}
      {...props}
    >
      {children ?? (
        <>
          <BookIcon className="size-3.5" />
          <span>
            {count} {label}
          </span>
          <ChevronDownIcon className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </>
      )}
    </Collapsible.Trigger>
  );
}

export type SourcesContentProps = ComponentProps<typeof Collapsible.Content>;

export function SourcesContent({ className, ...props }: SourcesContentProps) {
  return (
    <Collapsible.Content
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className,
      )}
      {...props}
    >
      <div className="mt-2 flex flex-col gap-2">{props.children}</div>
    </Collapsible.Content>
  );
}

export type SourceProps = ComponentProps<"a">;

export function Source({ children, className, ...props }: SourceProps) {
  return (
    <a
      className={cn(
        "flex items-center gap-2 text-muted-foreground transition-colors hover:text-foreground",
        className,
      )}
      rel="noreferrer"
      target="_blank"
      {...props}
    >
      {children ?? (
        <>
          <BookIcon className="size-3.5" />
          <span className="block font-medium">{props.title}</span>
        </>
      )}
    </a>
  );
}
