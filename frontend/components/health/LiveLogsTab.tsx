"use client";

import { cn } from "@/components/ui";
import type { LogLevel, LogLine } from "@/lib/health/types";
import { useAdminLogs } from "@/lib/hooks/useHealth";
import { ArrowDownToLine, Pause, Play, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { LogTerminal, type LogTerminalHandle } from "./LogTerminal";
import { ToggleSwitch } from "./ToggleSwitch";

const LEVELS: ("all" | Lowercase<LogLevel>)[] = ["all", "info", "warn", "error"];

/**
 * LiveLogsTab — the "Live Logs" tab shared by every service drawer
 * (design frame 08). Toolbar: pause-scroll + scroll-to-bottom buttons, an
 * auto-scroll toggle, an ALL/INFO/WARN/ERROR level segment, and a grep filter;
 * body: the dark LogTerminal.
 */
export function LiveLogsTab() {
  const t = useTranslations("health.logs");
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("all");
  const [grep, setGrep] = useState("");
  const terminalRef = useRef<LogTerminalHandle>(null);

  const { lines } = useAdminLogs();

  const filtered = useMemo(() => {
    return (lines as LogLine[]).filter((l) => {
      if (level !== "all" && l.level.toLowerCase() !== level) return false;
      if (grep && !`${l.source} ${l.message}`.toLowerCase().includes(grep.toLowerCase()))
        return false;
      return true;
    });
  }, [lines, level, grep]);

  const effectiveAutoScroll = autoScroll && !paused;

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium transition-colors",
            paused
              ? "bg-accent-soft text-accent-soft-foreground"
              : "bg-surface text-foreground-secondary hover:bg-background-secondary",
          )}
        >
          {paused ? (
            <Play size={13} strokeWidth={2} aria-hidden />
          ) : (
            <Pause size={13} strokeWidth={2} aria-hidden />
          )}
          {paused ? t("resumeScroll") : t("pauseScroll")}
        </button>
        <button
          type="button"
          onClick={() => terminalRef.current?.scrollToBottom()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:bg-background-secondary"
        >
          <ArrowDownToLine size={13} strokeWidth={2} aria-hidden />
          {t("toBottom")}
        </button>

        <span className="inline-flex items-center gap-2 text-xs font-medium text-foreground-secondary">
          {t("autoScroll")}
          <ToggleSwitch checked={autoScroll} onChange={setAutoScroll} ariaLabel={t("autoScroll")} />
        </span>

        {/* Level segment */}
        <div className="inline-flex items-center gap-0.5 rounded-lg bg-(--surface-muted) p-0.5">
          {LEVELS.map((lv) => (
            <button
              key={lv}
              type="button"
              onClick={() => setLevel(lv)}
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-semibold uppercase transition-colors",
                level === lv
                  ? "bg-surface text-foreground shadow-sm"
                  : "text-foreground-tertiary hover:text-foreground",
              )}
            >
              {t(`levels.${lv}`)}
            </button>
          ))}
        </div>

        {/* Grep */}
        <div className="relative ml-auto min-w-[140px] flex-1">
          <Search
            size={13}
            strokeWidth={2}
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-tertiary"
          />
          <input
            value={grep}
            onChange={(e) => setGrep(e.target.value)}
            placeholder={t("filterPlaceholder")}
            className="w-full rounded-lg border border-border bg-surface py-1.5 pl-8 pr-2.5 text-xs text-foreground outline-none placeholder:text-foreground-tertiary focus:border-field-border-focus"
          />
        </div>
      </div>

      {/* Terminal */}
      <LogTerminal
        ref={terminalRef}
        lines={filtered}
        autoScroll={effectiveAutoScroll}
        className="h-[60vh] flex-1"
      />
    </div>
  );
}
