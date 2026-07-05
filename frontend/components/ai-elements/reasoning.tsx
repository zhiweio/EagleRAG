"use client";

import { BrainIcon, ChevronDownIcon } from "lucide-react";
import { Collapsible } from "radix-ui";
import { type ComponentProps, createContext, useContext, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { Response } from "./response";
import { ThinkingLabel } from "./thinking-indicator";

type ReasoningContextValue = { isStreaming: boolean; duration: number };

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

function useReasoning() {
  const ctx = useContext(ReasoningContext);
  if (!ctx) throw new Error("Reasoning components must be used within <Reasoning>");
  return ctx;
}

export type ReasoningProps = ComponentProps<typeof Collapsible.Root> & {
  isStreaming?: boolean;
  duration?: number;
};

/**
 * A collapsible panel for free-form model reasoning tokens. Auto-opens while
 * streaming and collapses shortly after completion.
 */
export function Reasoning({
  className,
  isStreaming = false,
  duration = 0,
  open,
  defaultOpen = true,
  onOpenChange,
  children,
  ...props
}: ReasoningProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const hasAutoClosed = useRef(false);

  useEffect(() => {
    if (!isStreaming && !hasAutoClosed.current && open === undefined) {
      hasAutoClosed.current = true;
      const t = setTimeout(() => setInternalOpen(false), 800);
      return () => clearTimeout(t);
    }
  }, [isStreaming, open]);

  const handleOpenChange = (next: boolean) => {
    setInternalOpen(next);
    onOpenChange?.(next);
  };

  return (
    <ReasoningContext.Provider value={{ isStreaming, duration }}>
      <Collapsible.Root
        className={cn("not-prose text-sm", className)}
        onOpenChange={handleOpenChange}
        open={open ?? internalOpen}
        {...props}
      >
        {children}
      </Collapsible.Root>
    </ReasoningContext.Provider>
  );
}

export type ReasoningTriggerProps = ComponentProps<typeof Collapsible.Trigger>;

export function ReasoningTrigger({ className, children, ...props }: ReasoningTriggerProps) {
  const { isStreaming, duration } = useReasoning();
  return (
    <Collapsible.Trigger
      className={cn(
        "group flex items-center gap-1.5 text-muted-foreground text-xs transition-colors hover:text-foreground",
        className,
      )}
      {...props}
    >
      {children ?? (
        <>
          {isStreaming ? (
            <ThinkingLabel active className="gap-1.5">
              Thinking
            </ThinkingLabel>
          ) : (
            <>
              <BrainIcon className="size-3.5" />
              <span>{duration ? `Thought for ${duration}s` : "Reasoning"}</span>
            </>
          )}
          <ChevronDownIcon className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </>
      )}
    </Collapsible.Trigger>
  );
}

export type ReasoningContentProps = Omit<ComponentProps<typeof Collapsible.Content>, "children"> & {
  children: string;
};

export function ReasoningContent({ className, children, ...props }: ReasoningContentProps) {
  return (
    <Collapsible.Content
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className,
      )}
      {...props}
    >
      <div className="mt-2 border-border border-l pl-3 text-muted-foreground">
        <Response className="text-muted-foreground text-xs">{children}</Response>
      </div>
    </Collapsible.Content>
  );
}
