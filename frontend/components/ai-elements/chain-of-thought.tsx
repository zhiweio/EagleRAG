"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BrainIcon, ChevronDownIcon, DotIcon } from "lucide-react";
import { Collapsible } from "radix-ui";
import { type ComponentProps, createContext, memo } from "react";

import { cn } from "@/lib/utils";
import { ThinkingShimmerText, ThinkingSparkle } from "./thinking-indicator";

type ChainOfThoughtContextValue = { open: boolean };

const ChainOfThoughtContext = createContext<ChainOfThoughtContextValue>({ open: false });

export type ChainOfThoughtProps = ComponentProps<typeof Collapsible.Root> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

/**
 * A collapsible retrieval "thinking" timeline — the RAG-native reasoning trace
 * (route → recall → attach → rerank → generate) rendered as illuminated steps.
 */
export const ChainOfThought = memo(
  ({
    className,
    open,
    defaultOpen = true,
    onOpenChange,
    children,
    ...props
  }: ChainOfThoughtProps) => (
    <Collapsible.Root
      className={cn(
        "not-prose w-full rounded-xl border border-border bg-surface/60 text-sm",
        className,
      )}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      open={open}
      {...props}
    >
      <ChainOfThoughtContext.Provider value={{ open: open ?? defaultOpen }}>
        {children}
      </ChainOfThoughtContext.Provider>
    </Collapsible.Root>
  ),
);
ChainOfThought.displayName = "ChainOfThought";

export type ChainOfThoughtHeaderProps = ComponentProps<typeof Collapsible.Trigger> & {
  /** Gemini-style shimmer on the header label while the trace is still streaming. */
  streaming?: boolean;
};

export function ChainOfThoughtHeader({
  children,
  className,
  streaming = false,
  ...props
}: ChainOfThoughtHeaderProps) {
  return (
    <Collapsible.Trigger
      className={cn(
        "group flex w-full items-center gap-2 px-3 py-2.5 text-left font-medium text-xs transition-colors hover:text-foreground",
        streaming ? "text-foreground-secondary" : "text-muted-foreground",
        className,
      )}
      {...props}
    >
      {streaming ? <ThinkingSparkle /> : <BrainIcon className="size-4 shrink-0 text-primary" />}
      <span className="min-w-0 flex-1">
        {streaming ? (
          <ThinkingShimmerText>{children ?? "Thinking"}</ThinkingShimmerText>
        ) : (
          (children ?? "Chain of thought")
        )}
      </span>
      <ChevronDownIcon className="size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180" />
    </Collapsible.Trigger>
  );
}

export type ChainOfThoughtContentProps = ComponentProps<typeof Collapsible.Content>;

export function ChainOfThoughtContent({
  children,
  className,
  ...props
}: ChainOfThoughtContentProps) {
  return (
    <Collapsible.Content
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className,
      )}
      {...props}
    >
      <div className={cn("space-y-1 px-3 pt-1 pb-3")}>{children}</div>
    </Collapsible.Content>
  );
}

export type ChainOfThoughtStepStatus = "complete" | "active" | "pending";

export type ChainOfThoughtStepProps = ComponentProps<"div"> & {
  icon?: React.ComponentType<{ className?: string }>;
  label: React.ReactNode;
  description?: React.ReactNode;
  status?: ChainOfThoughtStepStatus;
};

const statusStyles: Record<ChainOfThoughtStepStatus, string> = {
  complete: "text-foreground",
  active: "text-foreground",
  pending: "text-muted-foreground",
};

export function ChainOfThoughtStep({
  icon: Icon = DotIcon,
  label,
  description,
  status = "complete",
  className,
  children,
  ...props
}: ChainOfThoughtStepProps) {
  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "flex gap-2.5 text-sm",
        "before:absolute before:top-7 before:bottom-0 before:left-[9px] before:w-px before:bg-border last:before:hidden",
        "relative pb-3 last:pb-0",
        statusStyles[status],
        className,
      )}
      initial={{ opacity: 0, y: 4 }}
      transition={{ duration: 0.2 }}
      {...(props as ComponentProps<typeof motion.div>)}
    >
      <span
        className={cn(
          "z-10 mt-0.5 flex size-[19px] shrink-0 items-center justify-center rounded-full border bg-surface",
          status === "active"
            ? "border-accent/50 text-accent thinking-step-ring"
            : status === "complete"
              ? "border-primary/40 text-primary"
              : "border-border text-muted-foreground",
        )}
      >
        <Icon className={cn("size-3", status === "active" && "thinking-step-icon")} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2 font-medium text-xs">
          {status === "active" ? (
            <ThinkingShimmerText className="text-xs" withDots={false}>
              {label}
            </ThinkingShimmerText>
          ) : (
            label
          )}
        </div>
        {description ? (
          <div className="text-muted-foreground text-xs leading-relaxed">{description}</div>
        ) : null}
        {children}
      </div>
    </motion.div>
  );
}

export type ChainOfThoughtSearchResultsProps = ComponentProps<"div">;

export function ChainOfThoughtSearchResults({
  className,
  ...props
}: ChainOfThoughtSearchResultsProps) {
  return <div className={cn("flex flex-wrap gap-1.5", className)} {...props} />;
}

export type ChainOfThoughtSearchResultProps = ComponentProps<"button"> & {
  tone?: "text" | "visual";
};

export function ChainOfThoughtSearchResult({
  className,
  tone = "text",
  children,
  ...props
}: ChainOfThoughtSearchResultProps) {
  return (
    <button
      className={cn(
        "inline-flex max-w-56 items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10.5px] transition-colors",
        tone === "visual"
          ? "bg-violet-100 text-violet-700 hover:bg-violet-200"
          : "bg-accent-soft text-accent-soft-foreground hover:bg-accent-soft-hover",
        className,
      )}
      type="button"
      {...props}
    >
      {children}
    </button>
  );
}

export type ChainOfThoughtStepGroupProps = ComponentProps<"div"> & {
  label: React.ReactNode;
};

/** Labeled subsection inside a step (e.g. rerank text_top / visual_top groups). */
export function ChainOfThoughtStepGroup({
  label,
  className,
  children,
  ...props
}: ChainOfThoughtStepGroupProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)} {...props}>
      <span className="font-medium text-[10px] text-muted-foreground uppercase tracking-wider">
        {label}
      </span>
      {children}
    </div>
  );
}

export type ChainOfThoughtVisualThumbProps = Omit<ComponentProps<"button">, "children"> & {
  src: string;
  alt: string;
  /** 1-based rerank rank shown on the thumbnail corner. */
  rank?: number;
};

/** Ranked visual slice preview for rerank `visual_top` readouts. */
export function ChainOfThoughtVisualThumb({
  src,
  alt,
  rank,
  className,
  type = "button",
  ...props
}: ChainOfThoughtVisualThumbProps) {
  return (
    <button
      className={cn(
        "group/thumb relative shrink-0 cursor-pointer rounded-md text-left transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/60",
        className,
      )}
      title={alt}
      type={type}
      {...props}
    >
      <div className="relative h-11 w-11 overflow-hidden rounded-md border border-violet-200/70 bg-violet-50/80 shadow-sm ring-1 ring-violet-100 transition-[transform,box-shadow] group-hover/thumb:scale-[1.03] group-hover/thumb:shadow-md">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img alt={alt} className="h-full w-full object-cover" loading="lazy" src={src} />
        {rank != null ? (
          <span
            aria-hidden
            className="absolute top-0.5 right-0.5 z-10 flex size-[15px] items-center justify-center rounded-full bg-violet-600 font-semibold text-[8.5px] text-white shadow-sm ring-1 ring-white/80"
          >
            {rank}
          </span>
        ) : null}
      </div>
    </button>
  );
}

export function ChainOfThoughtAnimated({ children }: { children: React.ReactNode }) {
  return (
    <AnimatePresence initial={false} mode="popLayout">
      {children}
    </AnimatePresence>
  );
}

export { ChainOfThoughtContext };
