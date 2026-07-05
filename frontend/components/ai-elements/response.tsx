"use client";

import { createMathPlugin } from "@streamdown/math";
import { type ComponentProps, memo } from "react";
import { Streamdown } from "streamdown";
import "katex/dist/katex.min.css";

import { cn } from "@/lib/utils";

/** KaTeX via @streamdown/math; enable $...$ for inline math from LLM output. */
const mathPlugin = createMathPlugin({ singleDollarTextMath: true });

export type ResponseProps = ComponentProps<typeof Streamdown>;

/**
 * Streaming-friendly Markdown renderer for assistant answers.
 *
 * Wraps `streamdown` (GFM + code highlighting + hardened links) with prose
 * spacing tuned for the light theme. Memoized so re-renders only occur when the
 * markdown string actually changes during token streaming.
 */
export const Response = memo(
  ({ className, plugins, ...props }: ResponseProps) => (
    <Streamdown
      plugins={{ math: mathPlugin, ...plugins }}
      className={cn(
        "size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        "prose-sm max-w-none text-foreground",
        "[&_.katex-display]:my-3 [&_.katex-display]:overflow-x-auto",
        "[&_p]:my-2 [&_p]:leading-relaxed",
        "[&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:font-semibold [&_h1]:text-base",
        "[&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:font-semibold [&_h2]:text-[15px]",
        "[&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:font-semibold [&_h3]:text-sm",
        "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
        "[&_li]:my-0.5",
        "[&_a]:font-medium [&_a]:text-primary [&_a]:underline-offset-2 hover:[&_a]:underline",
        "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em]",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs",
        "[&_th]:border [&_th]:border-border [&_th]:bg-secondary [&_th]:px-2 [&_th]:py-1 [&_th]:text-left",
        "[&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1",
        className,
      )}
      {...props}
    />
  ),
  (prev, next) => prev.children === next.children,
);

Response.displayName = "Response";
