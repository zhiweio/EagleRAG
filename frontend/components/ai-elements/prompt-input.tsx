"use client";

import { Loader2Icon, SendIcon, SquareIcon, XIcon } from "lucide-react";
import {
  type ComponentProps,
  type KeyboardEvent,
  type Ref,
  useCallback,
  useEffect,
  useRef,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Assign a value to a callback or object ref (used to merge internal + external refs). */
function setRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value);
  else if (ref) (ref as { current: T | null }).current = value;
}

export type PromptInputProps = ComponentProps<"form">;

/** A composer form. Submits on Enter (Shift+Enter inserts a newline). */
export function PromptInput({ className, ...props }: PromptInputProps) {
  return (
    <form
      className={cn(
        "flex w-full flex-col rounded-2xl border border-border bg-surface shadow-sm transition-colors focus-within:border-field-border-focus",
        className,
      )}
      {...props}
    />
  );
}

export type PromptInputBodyProps = ComponentProps<"div">;

export function PromptInputBody({ className, ...props }: PromptInputBodyProps) {
  return <div className={cn("flex flex-col gap-2 px-3 pt-3", className)} {...props} />;
}

export type PromptInputTextareaProps = ComponentProps<"textarea"> & {
  minHeight?: number;
  maxHeight?: number;
  /** Forwarded to the underlying textarea; merged with the internal auto-grow ref. */
  ref?: Ref<HTMLTextAreaElement>;
};

export function PromptInputTextarea({
  className,
  onKeyDown,
  minHeight = 44,
  maxHeight = 200,
  ref: externalRef,
  ...props
}: PromptInputTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const setRefs = useCallback(
    (node: HTMLTextAreaElement | null) => {
      ref.current = node;
      setRef(externalRef, node);
    },
    [externalRef],
  );

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [maxHeight]);

  // Keep the auto-grow height in sync with controlled value changes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: props.value drives the resize on controlled updates
  useEffect(() => {
    resize();
  }, [resize, props.value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <textarea
      className={cn(
        "w-full resize-none bg-transparent text-foreground text-sm leading-relaxed outline-none placeholder:text-field-placeholder",
        className,
      )}
      onInput={resize}
      onKeyDown={handleKeyDown}
      ref={setRefs}
      rows={1}
      style={{ minHeight, maxHeight }}
      {...props}
    />
  );
}

export type PromptInputToolbarProps = ComponentProps<"div">;

export function PromptInputToolbar({ className, ...props }: PromptInputToolbarProps) {
  return (
    <div
      className={cn("flex items-center justify-between gap-2 px-2 pb-2", className)}
      {...props}
    />
  );
}

export type PromptInputToolsProps = ComponentProps<"div">;

export function PromptInputTools({ className, ...props }: PromptInputToolsProps) {
  return <div className={cn("flex items-center gap-1", className)} {...props} />;
}

export type PromptInputButtonProps = ComponentProps<typeof Button>;

export function PromptInputButton({
  className,
  variant = "ghost",
  size,
  children,
  ...props
}: PromptInputButtonProps) {
  const resolvedSize = size ?? (children ? "sm" : "icon");
  return (
    <Button
      className={cn("text-muted-foreground hover:text-foreground", className)}
      size={resolvedSize}
      type="button"
      variant={variant}
      {...props}
    >
      {children}
    </Button>
  );
}

export type PromptInputSubmitStatus = "ready" | "submitted" | "streaming" | "error";

export type PromptInputSubmitProps = ComponentProps<typeof Button> & {
  status?: PromptInputSubmitStatus;
};

export function PromptInputSubmit({
  className,
  status = "ready",
  size = "icon",
  variant = "default",
  children,
  ...props
}: PromptInputSubmitProps) {
  // Send's glyph mass sits top-right; nudge so it reads centered in the circle.
  let icon = <SendIcon className="size-4 -translate-x-px translate-y-px" aria-hidden />;
  if (status === "submitted") icon = <Loader2Icon className="size-4 animate-spin" aria-hidden />;
  else if (status === "streaming") icon = <SquareIcon className="size-3.5" aria-hidden />;
  else if (status === "error") icon = <XIcon className="size-4" aria-hidden />;

  return (
    <Button
      className={cn("size-9 shrink-0 gap-0 rounded-full p-0", className)}
      size={size}
      type="submit"
      variant={variant}
      {...props}
    >
      {children ?? icon}
    </Button>
  );
}
