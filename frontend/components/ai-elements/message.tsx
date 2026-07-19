"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type MessageProps = ComponentProps<"div"> & {
  from: "user" | "assistant" | "system";
};

/** A single chat turn; user turns align right, assistant turns align left. */
export function Message({ className, from, ...props }: MessageProps) {
  return (
    <div
      className={cn(
        "group flex w-full items-end gap-2 py-3",
        from === "user" ? "is-user justify-end" : "is-assistant justify-start",
        className,
      )}
      data-role={from}
      {...props}
    />
  );
}

export type MessageContentProps = ComponentProps<"div"> & {
  variant?: "contained" | "flat";
};

export function MessageContent({
  children,
  className,
  variant = "contained",
  ...props
}: MessageContentProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 overflow-hidden text-sm",
        variant === "contained" && [
          "max-w-[85%] rounded-2xl px-4 py-3",
          "group-[.is-user]:rounded-tr-md group-[.is-user]:bg-primary group-[.is-user]:text-primary-foreground",
          "group-[.is-assistant]:rounded-tl-md group-[.is-assistant]:bg-secondary group-[.is-assistant]:text-foreground",
        ],
        variant === "flat" && [
          "max-w-[85%]",
          "group-[.is-assistant]:min-w-0 group-[.is-assistant]:flex-1 group-[.is-assistant]:max-w-[85%]",
          "group-[.is-user]:rounded-2xl group-[.is-user]:rounded-tr-md group-[.is-user]:bg-primary group-[.is-user]:px-4 group-[.is-user]:py-3 group-[.is-user]:text-primary-foreground",
          "group-[.is-assistant]:text-foreground",
        ],
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export type MessageAvatarProps = ComponentProps<"div"> & {
  children?: React.ReactNode;
};

export function MessageAvatar({ children, className, ...props }: MessageAvatarProps) {
  return (
    <div
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center self-start overflow-hidden rounded-full",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
