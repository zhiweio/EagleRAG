"use client";

import { cn } from "@/components/ui";
import type { LogLine } from "@/lib/health/types";
import { useAdminMcp, useMcpTools } from "@/lib/hooks/useHealth";
import { ArrowDownToLine, Pause, Play, Radio, Search, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { LogTerminal, type LogTerminalHandle } from "./LogTerminal";
import { DrawerPanel } from "./drawer-parts";

/** Tone color per tool name — gives each exposed tool a distinct identity. */
const TOOL_ACCENT: Record<string, { dot: string; text: string; bg: string }> = {
  query: { dot: "bg-accent", text: "text-accent", bg: "bg-accent-soft" },
  trace: { dot: "bg-warning", text: "text-warning", bg: "bg-warning-soft" },
  read: { dot: "bg-success", text: "text-success", bg: "bg-success-soft" },
  ingest: { dot: "bg-success", text: "text-success", bg: "bg-success-soft" },
};

function toolAccent(name: string) {
  return (
    TOOL_ACCENT[name] ?? {
      dot: "bg-foreground-tertiary",
      text: "text-foreground-secondary",
      bg: "bg-(--surface-muted)",
    }
  );
}

/**
 * McpServerDashboard — the "Dashboard" tab for the MCP server drawer.
 *
 * Live SSE-connections tile, exposed-tools list with per-tool accent colors
 * and parameter type annotations, and an embedded agent console.
 */
export function McpServerDashboard() {
  const tm = useTranslations("health.mcpDrawer");
  const tcn = useTranslations("health.console");
  const [grep, setGrep] = useState("");
  const [paused, setPaused] = useState(false);
  const terminalRef = useRef<LogTerminalHandle>(null);

  const mcpQuery = useAdminMcp(!paused);
  const toolsQuery = useMcpTools();
  const tools = toolsQuery.data?.tools ?? mcpQuery.data?.tools ?? [];
  const sseConnections = mcpQuery.data?.sse_connections ?? 0;
  const registered = mcpQuery.data?.registered ?? false;

  const consoleLogs: LogLine[] = (mcpQuery.data?.console_logs ?? []).map((c) => ({
    time: c.time.slice(11, 19) || c.time,
    level: "INFO" as const,
    source: "",
    message: c.message,
  }));

  const filtered = useMemo(
    () =>
      consoleLogs.filter((l) =>
        grep ? l.message.toLowerCase().includes(grep.toLowerCase()) : true,
      ),
    [consoleLogs, grep],
  );

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* ── SSE connections tile ──────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl border border-border bg-surface p-4">
        {/* Subtle ambient glow when active */}
        {sseConnections > 0 ? (
          <span
            aria-hidden
            className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-success/10 blur-2xl"
          />
        ) : null}
        <div className="relative flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className={cn(
                "relative flex h-11 w-11 items-center justify-center rounded-xl",
                sseConnections > 0
                  ? "bg-success-soft text-success-soft-foreground"
                  : "bg-(--surface-muted) text-foreground-tertiary",
              )}
            >
              <Radio size={20} strokeWidth={2} />
              {sseConnections > 0 ? (
                <span aria-hidden className="absolute -right-0.5 -top-0.5 flex h-3 w-3">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
                  <span className="relative inline-flex h-3 w-3 rounded-full border-2 border-surface bg-success" />
                </span>
              ) : null}
            </span>
            <div className="flex flex-col">
              <span className="text-sm font-medium text-foreground">{tm("sse.title")}</span>
              <span className="text-[11px] text-foreground-tertiary">{tm("sse.note")}</span>
            </div>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span
              className={cn(
                "text-3xl font-semibold leading-none tabular-nums",
                sseConnections > 0 ? "text-success" : "text-foreground",
              )}
            >
              {sseConnections}
            </span>
            <span className="text-xs text-foreground-tertiary">{tm("sse.unit")}</span>
          </div>
        </div>
      </div>

      {/* ── Exposed tools ─────────────────────────────────────────────── */}
      <DrawerPanel
        title={
          <div className="flex items-center gap-2">
            <Wrench size={14} strokeWidth={2} aria-hidden className="text-foreground-tertiary" />
            {tm("toolsTitle")}
          </div>
        }
        note={tm("toolsCount", { n: tools.length })}
        bodyClassName="flex flex-col gap-2"
      >
        {tools.length === 0 && !registered ? (
          <div className="flex items-center justify-center py-6 text-sm text-foreground-tertiary">
            {tm("toolsCount", { n: 0 })}
          </div>
        ) : null}
        {tools.map((tool) => {
          const props = tool.parameters?.properties as
            | Record<string, { type?: string; description?: string; enum?: unknown[] }>
            | undefined;
          const paramEntries = props ? Object.entries(props) : [];
          const required = (tool.parameters?.required as string[] | undefined) ?? [];
          const accent = toolAccent(tool.name);
          return (
            <div
              key={tool.name}
              className="group flex flex-col gap-2 rounded-xl border border-border bg-surface px-3.5 py-3 transition-colors hover:border-field-border-focus"
            >
              {/* Tool name row */}
              <div className="flex items-center gap-2">
                <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", accent.dot)} />
                <span className={cn("font-mono text-xs font-semibold", accent.text)}>
                  {tool.name}
                </span>
                <span className="ml-auto rounded-md bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wide text-foreground-tertiary">
                  tool
                </span>
              </div>
              {/* Description */}
              <span className="text-[11.5px] leading-relaxed text-foreground-secondary">
                {tool.description}
              </span>
              {/* Parameters with type annotations */}
              {paramEntries.length > 0 ? (
                <div className="flex flex-col gap-1.5 border-t border-border pt-2">
                  <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-tertiary">
                    {tm("paramPrefix")}
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {paramEntries.map(([pName, pDef]) => {
                      const isRequired = required.includes(pName);
                      const pType = pDef?.type ?? "any";
                      return (
                        <span
                          key={pName}
                          className="inline-flex items-center gap-1 rounded-md bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[10px]"
                        >
                          <span className="text-foreground-secondary">{pName}</span>
                          <span className="text-foreground-tertiary">:</span>
                          <span className="text-accent">{pType}</span>
                          {isRequired ? <span className="text-danger">*</span> : null}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </DrawerPanel>

      {/* ── Embedded console ──────────────────────────────────────────── */}
      <section className="overflow-hidden rounded-2xl border border-border">
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-(--surface-muted)/40 px-3 py-2">
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
            {paused ? tcn("resume") : tcn("pause")}
          </button>
          <button
            type="button"
            onClick={() => terminalRef.current?.scrollToBottom()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:bg-background-secondary"
          >
            <ArrowDownToLine size={13} strokeWidth={2} aria-hidden />
            {tcn("toBottom")}
          </button>
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
              placeholder={tcn("filterPlaceholder")}
              className="w-full rounded-lg border border-border bg-surface py-1.5 pl-8 pr-2.5 text-xs text-foreground outline-none placeholder:text-foreground-tertiary focus:border-field-border-focus"
            />
          </div>
        </div>
        <LogTerminal
          ref={terminalRef}
          lines={filtered}
          autoScroll={!paused}
          className={cn("h-[36vh]")}
        />
      </section>
    </div>
  );
}
