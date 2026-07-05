"use client";

import { ExternalLinkIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type WebPreviewProps = ComponentProps<"div">;

/** A framed inline preview surface for rendered HTML pages, tables, or PDFs. */
export function WebPreview({ className, ...props }: WebPreviewProps) {
  return (
    <div
      className={cn(
        "flex size-full flex-col overflow-hidden rounded-lg border border-border bg-surface",
        className,
      )}
      {...props}
    />
  );
}

export type WebPreviewNavigationProps = ComponentProps<"div">;

export function WebPreviewNavigation({ className, ...props }: WebPreviewNavigationProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 border-border border-b bg-secondary/60 px-2 py-1.5",
        className,
      )}
      {...props}
    />
  );
}

export type WebPreviewUrlProps = ComponentProps<"input"> & {
  href?: string;
};

export function WebPreviewUrl({ className, href, value, ...props }: WebPreviewUrlProps) {
  return (
    <>
      <input
        className={cn(
          "h-7 min-w-0 flex-1 truncate rounded-md bg-surface px-2 font-mono text-[11px] text-muted-foreground outline-none",
          className,
        )}
        readOnly
        value={value}
        {...props}
      />
      {href ? (
        <Button asChild size="icon" variant="ghost" className="size-7 text-muted-foreground">
          <a href={href} rel="noreferrer" target="_blank" aria-label="Open in new tab">
            <ExternalLinkIcon className="size-3.5" />
          </a>
        </Button>
      ) : null}
    </>
  );
}

export type WebPreviewBodyProps = ComponentProps<"iframe">;

export function WebPreviewBody({ className, src, srcDoc, title, ...props }: WebPreviewBodyProps) {
  return (
    <iframe
      className={cn("size-full flex-1 border-0 bg-surface", className)}
      sandbox="allow-scripts allow-same-origin allow-popups"
      src={src}
      srcDoc={srcDoc}
      title={title ?? "preview"}
      {...props}
    />
  );
}
