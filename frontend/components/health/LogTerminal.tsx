"use client";

import { cn } from "@/components/ui";
import type { LogLevel, LogLine } from "@/lib/health/types";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

/**
 * LogTerminal — dark, monospace log viewport shared by the Live Logs tab
 * (design frame 08) and the MCP embedded console (frame 07). Renders each line
 * as `time [LEVEL] source message`, with the level colored and ERROR rows
 * given a red highlight band.
 *
 * - `autoScroll` (default true): auto-scrolls to the bottom when new logs arrive.
 * - `scrollToBottom()` can be called imperatively via ref (used by the "to bottom" button).
 */

const LEVEL_TEXT: Record<LogLevel, string> = {
  INFO: "text-sky-400",
  DEBUG: "text-zinc-500",
  WARN: "text-amber-400",
  ERROR: "text-red-400",
};

export type LogTerminalHandle = { scrollToBottom: () => void };

export const LogTerminal = forwardRef<
  LogTerminalHandle,
  { lines: LogLine[]; className?: string; autoScroll?: boolean }
>(function LogTerminal({ lines, className, autoScroll = true }, ref) {
  const containerRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => ({
    scrollToBottom: () => {
      const el = containerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    },
  }));

  // lines is a prop (changes when new logs arrive) and must be a dependency to trigger auto-scroll to the bottom.
  // biome-ignore lint/correctness/useExhaustiveDependencies: lines is a prop that changes on new logs
  useEffect(() => {
    if (autoScroll) {
      const el = containerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [lines, autoScroll]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "overflow-auto bg-background-inverse p-3 font-mono text-xs leading-relaxed",
        className,
      )}
    >
      {lines.length === 0 ? (
        <p className="text-foreground-inverse/40">—</p>
      ) : (
        <div className="flex flex-col">
          {lines.map((line, i) => (
            <div
              key={`${line.time}-${i}`}
              className={cn(
                "flex gap-2 whitespace-pre-wrap break-all rounded px-1 py-0.5",
                line.level === "ERROR" && "bg-red-500/15",
              )}
            >
              <span className="shrink-0 text-foreground-inverse/40">{line.time}</span>
              <span className={cn("shrink-0 font-semibold", LEVEL_TEXT[line.level])}>
                [{line.level}]
              </span>
              {line.source ? (
                <span className="shrink-0 text-foreground-inverse/60">{line.source}</span>
              ) : null}
              <span
                className={cn(
                  line.level === "ERROR" ? "text-red-300" : "text-foreground-inverse/90",
                )}
              >
                {line.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
