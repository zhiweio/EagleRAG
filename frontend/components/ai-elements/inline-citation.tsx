"use client";

import { HoverCard } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type InlineCitationProps = ComponentProps<"span">;

/** Wraps a run of answer text together with its trailing `[n]` citation badges. */
export function InlineCitation({ className, ...props }: InlineCitationProps) {
  return <span className={cn("inline items-center gap-1", className)} {...props} />;
}

export type InlineCitationTextProps = ComponentProps<"span">;

export function InlineCitationText({ className, ...props }: InlineCitationTextProps) {
  return (
    <span className={cn("transition-colors group-hover:bg-accent-soft", className)} {...props} />
  );
}

export type InlineCitationCardProps = ComponentProps<typeof HoverCard.Root>;

export function InlineCitationCard(props: InlineCitationCardProps) {
  return <HoverCard.Root closeDelay={80} openDelay={120} {...props} />;
}

export type InlineCitationCardTriggerProps = ComponentProps<"button"> & {
  label: React.ReactNode;
};

export function InlineCitationCardTrigger({
  className,
  label,
  ...props
}: InlineCitationCardTriggerProps) {
  return (
    <HoverCard.Trigger asChild>
      <button
        className={cn(
          "ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-soft px-1 align-super font-mono font-medium text-[10px] text-accent-soft-foreground leading-none transition-colors hover:bg-primary hover:text-primary-foreground",
          className,
        )}
        type="button"
        {...props}
      >
        {label}
      </button>
    </HoverCard.Trigger>
  );
}

export type InlineCitationCardBodyProps = ComponentProps<typeof HoverCard.Content>;

export function InlineCitationCardBody({ className, ...props }: InlineCitationCardBodyProps) {
  return (
    <HoverCard.Portal>
      <HoverCard.Content
        align="start"
        className={cn(
          "fade-card z-50 w-80 rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg",
          className,
        )}
        sideOffset={6}
        {...props}
      />
    </HoverCard.Portal>
  );
}

export type InlineCitationSourceProps = ComponentProps<"div"> & {
  title?: string;
  url?: string;
  description?: string;
};

export function InlineCitationSource({
  title,
  url,
  description,
  className,
  children,
  ...props
}: InlineCitationSourceProps) {
  return (
    <div className={cn("space-y-1", className)} {...props}>
      {title ? (
        <p className="truncate font-medium text-sm leading-tight" title={title}>
          {title}
        </p>
      ) : null}
      {url ? (
        <p className="truncate break-all font-mono text-[11px] text-muted-foreground" title={url}>
          {url}
        </p>
      ) : null}
      {description ? (
        <p className="line-clamp-3 text-muted-foreground text-xs leading-relaxed">{description}</p>
      ) : null}
      {children}
    </div>
  );
}

export type InlineCitationQuoteProps = ComponentProps<"blockquote">;

export function InlineCitationQuote({ children, className, ...props }: InlineCitationQuoteProps) {
  return (
    <blockquote
      className={cn(
        "mt-2 border-border border-l-2 pl-2 text-muted-foreground text-xs italic",
        className,
      )}
      {...props}
    >
      {children}
    </blockquote>
  );
}
