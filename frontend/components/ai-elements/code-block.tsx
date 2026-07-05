"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { type ComponentProps, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type CodeBlockProps = ComponentProps<"div"> & {
  code: string;
  language?: string;
  showCopy?: boolean;
};

/**
 * A copyable fenced code block for standalone snippets. Streamed answer bodies
 * highlight code via `Response`/streamdown; this is for evidence/JSON panels.
 */
export function CodeBlock({
  code,
  language,
  showCopy = true,
  className,
  children,
  ...props
}: CodeBlockProps) {
  return (
    <div
      className={cn(
        "not-prose group relative overflow-hidden rounded-lg border border-border bg-muted",
        className,
      )}
      {...props}
    >
      {language ? (
        <div className="flex items-center justify-between border-border border-b px-3 py-1.5">
          <span className="font-mono text-[11px] text-muted-foreground">{language}</span>
        </div>
      ) : null}
      <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed">
        <code>{code}</code>
      </pre>
      {showCopy ? (
        <div className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100">
          <CodeBlockCopyButton code={code} />
        </div>
      ) : null}
      {children}
    </div>
  );
}

export type CodeBlockCopyButtonProps = ComponentProps<typeof Button> & {
  code: string;
};

export function CodeBlockCopyButton({ code, className, ...props }: CodeBlockCopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <Button
      className={cn("size-7 text-muted-foreground", className)}
      onClick={onCopy}
      size="icon"
      type="button"
      variant="ghost"
      {...props}
    >
      {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
    </Button>
  );
}
