"use client";

import { Response } from "@/components/ai-elements/response";
import { cn } from "@/lib/utils";

interface MarkdownSnippetProps {
  children: string;
  className?: string;
  lineClamp?: 2 | 3 | 4;
}

const LINE_CLAMP: Record<NonNullable<MarkdownSnippetProps["lineClamp"]>, string> = {
  2: "line-clamp-2",
  3: "line-clamp-3",
  4: "line-clamp-4",
};

/** Compact markdown + LaTeX for evidence rail snippets (sources / structure). */
export function MarkdownSnippet({ children, className, lineClamp }: MarkdownSnippetProps) {
  return (
    <Response
      mode="static"
      className={cn(
        "text-foreground-secondary [&_p]:my-0 [&_p]:leading-relaxed",
        "[&_.katex-display]:my-2 [&_.katex-display]:overflow-x-auto",
        lineClamp && LINE_CLAMP[lineClamp],
        className,
      )}
    >
      {children}
    </Response>
  );
}
