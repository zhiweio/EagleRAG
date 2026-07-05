"use client";

import { Loader2Icon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type LoaderProps = ComponentProps<"div"> & {
  size?: number;
};

/** Spinning loader used while the assistant is preparing a response. */
export function Loader({ className, size = 16, ...props }: LoaderProps) {
  return (
    <div
      className={cn("inline-flex items-center justify-center text-muted-foreground", className)}
      {...props}
    >
      <Loader2Icon className="animate-spin" size={size} />
    </div>
  );
}
