"use client";

import { cn } from "@/components/ui";
import { API_BASE } from "@/lib/api/client";
import type { McpToolDefinition } from "@/lib/api/generated/types.gen";
import { useAdminMcp, useMcpTools } from "@/lib/hooks/useHealth";
import {
  Activity,
  Check,
  ChevronDown,
  Copy,
  FileJson,
  Plug,
  Radio,
  Terminal,
  Wrench,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

/** Per-tool accent color for visual differentiation. */
const TOOL_ACCENT: Record<string, { dot: string; text: string; ring: string }> = {
  ingest: { dot: "bg-success", text: "text-success", ring: "hover:border-success/30" },
  query: { dot: "bg-accent", text: "text-accent", ring: "hover:border-accent/30" },
  retrieve_text: { dot: "bg-warning", text: "text-warning", ring: "hover:border-warning/30" },
  retrieve_visual: { dot: "bg-success", text: "text-success", ring: "hover:border-success/30" },
};

function toolAccent(name: string) {
  return (
    TOOL_ACCENT[name] ?? {
      dot: "bg-foreground-tertiary",
      text: "text-foreground-secondary",
      ring: "hover:border-field-border-focus",
    }
  );
}

/** Expandable tool card showing name, description, and parameter schema. */
function ToolCard({
  tool,
  index,
}: {
  tool: McpToolDefinition;
  index: number;
}) {
  const t = useTranslations("health.mcpConfig");
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const accent = toolAccent(tool.name);

  const props = tool.parameters?.properties as
    | Record<string, { type?: string; description?: string; enum?: unknown[] }>
    | undefined;
  const paramEntries = props ? Object.entries(props) : [];
  const required = (tool.parameters?.required as string[] | undefined) ?? [];
  const hasParams = paramEntries.length > 0;

  const copySchema = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(JSON.stringify(tool, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // ignore
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border border-border bg-surface transition-colors",
        accent.ring,
      )}
      style={{ animationDelay: `${index * 40}ms` }}
    >
      {/* Header row — clickable to expand/collapse */}
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-2.5 px-3.5 py-2.5 text-left"
      >
        <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", accent.dot)} />
        <span className={cn("font-mono text-[12px] font-semibold", accent.text)}>{tool.name}</span>
        <span className="ml-auto flex items-center gap-2">
          {hasParams ? (
            <span className="text-[10px] text-foreground-tertiary">
              {paramEntries.length} {paramEntries.length === 1 ? "param" : "params"}
            </span>
          ) : (
            <span className="text-[10px] text-foreground-tertiary">{t("toolNoParams")}</span>
          )}
          <ChevronDown
            size={14}
            strokeWidth={2}
            aria-hidden
            className={cn(
              "shrink-0 text-foreground-tertiary transition-transform duration-200",
              expanded && "rotate-180",
            )}
          />
        </span>
      </button>

      {/* Expandable body */}
      {expanded ? (
        <div className="flex flex-col gap-2.5 border-t border-border px-3.5 py-3">
          {/* Description */}
          <p className="text-[11.5px] leading-relaxed text-foreground-secondary">
            {tool.description}
          </p>

          {/* Parameters */}
          {hasParams ? (
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-tertiary">
                  Parameters
                </span>
                <button
                  type="button"
                  onClick={copySchema}
                  className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-foreground-tertiary transition-colors hover:bg-background-secondary hover:text-foreground"
                >
                  {copied ? (
                    <Check size={10} strokeWidth={2.5} aria-hidden className="text-success" />
                  ) : (
                    <Copy size={10} strokeWidth={2} aria-hidden />
                  )}
                  {copied ? t("toolSchemaCopied") : t("toolCopySchema")}
                </button>
              </div>
              <div className="flex flex-col gap-1">
                {paramEntries.map(([pName, pDef]) => {
                  const isRequired = required.includes(pName);
                  const pType = pDef?.type ?? "any";
                  return (
                    <div
                      key={pName}
                      className="flex items-center gap-2 rounded-lg bg-(--surface-muted)/50 px-2.5 py-1.5"
                    >
                      <span className="font-mono text-[11px] font-medium text-foreground-secondary">
                        {pName}
                      </span>
                      <span className="text-foreground-tertiary">:</span>
                      <span className="font-mono text-[11px] text-accent">{pType}</span>
                      <span
                        className={cn(
                          "ml-auto rounded px-1.5 py-0.5 text-[9px] font-medium uppercase",
                          isRequired
                            ? "bg-danger-soft text-danger-soft-foreground"
                            : "bg-(--surface-muted) text-foreground-tertiary",
                        )}
                      >
                        {isRequired ? t("toolParamRequired") : t("toolParamOptional")}
                      </span>
                    </div>
                  );
                })}
              </div>
              {/* Enum values for params that have them */}
              {paramEntries
                .filter(([, d]) => d?.enum && d.enum.length > 0)
                .map(([pName, pDef]) => (
                  <div key={`enum-${pName}`} className="flex flex-wrap items-center gap-1">
                    <span className="text-[10px] text-foreground-tertiary">{pName}:</span>
                    {(pDef?.enum as string[]).map((v) => (
                      <span
                        key={v}
                        className="rounded bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[10px] text-foreground-secondary"
                      >
                        {v}
                      </span>
                    ))}
                  </div>
                ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Format the transport label from live backend config. */
function transportLabel(transport: string | null | undefined): string {
  if (transport === "http") return "Streamable HTTP (JSON-RPC)";
  if (transport === "stdio") return "stdio";
  return transport ?? "—";
}

/** Format the mode label from live backend config. */
function modeLabel(
  stateless: boolean | null | undefined,
  json: boolean | null | undefined,
): string {
  const parts: string[] = [];
  if (stateless) parts.push("Stateless");
  if (json) parts.push("JSON-only");
  return parts.length > 0 ? parts.join(" · ") : "—";
}

/** Compact stat chip used in the card header row. */
function StatChip({
  icon: Icon,
  value,
  label,
  tone = "default",
}: {
  icon: typeof Activity;
  value: number | string;
  label: string;
  tone?: "default" | "success" | "accent";
}) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "accent" ? "text-accent" : "text-foreground";
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-(--surface-muted)/40 px-3 py-2">
      <Icon size={14} strokeWidth={2} aria-hidden className={cn("shrink-0", toneClass)} />
      <div className="flex items-baseline gap-1.5">
        <span className={cn("text-base font-semibold tabular-nums leading-none", toneClass)}>
          {value}
        </span>
        <span className="text-[11px] text-foreground-tertiary">{label}</span>
      </div>
    </div>
  );
}

/** Metadata row item (label + mono value). */
function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wide text-foreground-tertiary">
        {label}
      </span>
      <span className="font-mono text-[12px] font-medium text-foreground-secondary">{value}</span>
    </div>
  );
}

/** Inline copy button used inside the dark code blocks. */
function InlineCopy({
  onClick,
  copied,
  copiedLabel,
  defaultLabel,
}: {
  onClick: () => void;
  copied: boolean;
  copiedLabel: string;
  defaultLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs font-medium text-white/80 transition-colors hover:bg-white/10 hover:text-white"
    >
      {copied ? (
        <Check size={13} strokeWidth={2.5} aria-hidden className="text-emerald-400" />
      ) : (
        <Copy size={13} strokeWidth={2} aria-hidden />
      )}
      {copied ? copiedLabel : defaultLabel}
    </button>
  );
}

/**
 * McpConfigCard — the "MCP Server Configuration" panel on the health page.
 *
 * A refined, information-dense card that surfaces live MCP runtime state
 * (registration status, tool count, SSE connections) alongside the endpoint
 * URL and a copy-paste-ready JSON config snippet for quick agent onboarding.
 */
export function McpConfigCard() {
  const t = useTranslations("health.mcpConfig");
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  // Live data — same hooks used by the drawer dashboard.
  const mcpQuery = useAdminMcp();
  const toolsQuery = useMcpTools();
  const registered = mcpQuery.data?.registered ?? false;
  const tools: McpToolDefinition[] = toolsQuery.data?.tools ?? mcpQuery.data?.tools ?? [];
  const sseConnections = mcpQuery.data?.sse_connections ?? 0;
  const toolCount = tools.length;

  // Live transport metadata from backend.
  const endpointPath = mcpQuery.data?.endpoint_path ?? "/mcp";
  const mcpEndpoint = `${API_BASE}${endpointPath}`;
  const mcpPort = mcpQuery.data?.port;
  const mcpTransport = transportLabel(mcpQuery.data?.transport);
  const mcpProtocol = mcpQuery.data?.protocol_version ?? "—";
  const mcpMode = modeLabel(mcpQuery.data?.stateless_http, mcpQuery.data?.json_response);

  // JSON config snippet for quick agent onboarding (Claude Desktop / etc.).
  // Streamable HTTP transport: clients connect via `url` only (no transport field).
  const jsonConfig = useMemo(
    () =>
      JSON.stringify(
        {
          mcpServers: {
            "eagle-rag": {
              url: mcpEndpoint,
            },
          },
        },
        null,
        2,
      ),
    [mcpEndpoint],
  );

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(mcpEndpoint);
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 1600);
    } catch {
      // Clipboard may be unavailable (insecure context) — ignore.
    }
  };

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(jsonConfig);
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 1600);
    } catch {
      // ignore
    }
  };

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border bg-surface p-5">
      {/* ── Header: icon + title + status ─────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={cn(
              "relative flex h-11 w-11 items-center justify-center rounded-xl",
              registered
                ? "bg-accent-soft text-accent-soft-foreground"
                : "bg-(--surface-muted) text-foreground-tertiary",
            )}
          >
            <Plug size={20} strokeWidth={2} />
            {registered ? (
              <span aria-hidden className="absolute -right-0.5 -top-0.5 flex h-3.5 w-3.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
                <span className="relative inline-flex h-3.5 w-3.5 rounded-full border-2 border-surface bg-success" />
              </span>
            ) : null}
          </span>
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <h2 className="text-[15px] font-semibold text-foreground">{t("title")}</h2>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  registered
                    ? "bg-success-soft text-success-soft-foreground"
                    : "bg-(--surface-muted) text-foreground-tertiary",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    registered ? "bg-success" : "bg-foreground-tertiary",
                  )}
                />
                {registered ? t("statusOnline") : t("statusOffline")}
              </span>
            </div>
            <p className="text-[12.5px] leading-relaxed text-foreground-secondary">{t("desc")}</p>
          </div>
        </div>
      </div>

      {/* ── Stat chips row ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <StatChip icon={Wrench} value={toolCount} label={t("toolsLabel")} tone="accent" />
        <StatChip
          icon={Radio}
          value={sseConnections}
          label={t("connectionsLabel")}
          tone={sseConnections > 0 ? "success" : "default"}
        />
        <StatChip icon={Activity} value={t("badge")} label="" tone="default" />
      </div>

      {/* ── Metadata grid ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-xl border border-border bg-(--surface-muted)/30 px-4 py-3 sm:grid-cols-4">
        <MetaItem label={t("transportLabel")} value={mcpTransport} />
        <MetaItem label={t("protocolVersion")} value={mcpProtocol} />
        <MetaItem label={t("modeLabel")} value={mcpMode} />
        <MetaItem label={t("portLabel")} value={mcpPort != null ? String(mcpPort) : "—"} />
      </div>

      {/* ── Exposed tools ─────────────────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 px-1">
          <Wrench size={13} strokeWidth={2} aria-hidden className="text-foreground-tertiary" />
          <span className="text-[11px] font-medium uppercase tracking-wide text-foreground-tertiary">
            {t("toolsSectionTitle")}
          </span>
          <span className="text-[11px] text-foreground-tertiary">·</span>
          <span className="text-[11px] text-foreground-tertiary">
            {toolCount} {t("toolsLabel")}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:items-start">
          {tools.map((tool, i) => (
            <ToolCard key={tool.name} tool={tool} index={i} />
          ))}
        </div>
      </div>

      {/* ── Endpoint URL code block ───────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 px-1">
          <Terminal size={13} strokeWidth={2} aria-hidden className="text-foreground-tertiary" />
          <span className="text-[11px] font-medium uppercase tracking-wide text-foreground-tertiary">
            MCP Endpoint
          </span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl bg-background-inverse px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-success" />
            <code className="truncate font-mono text-[13px] text-white/90">{mcpEndpoint}</code>
          </div>
          <InlineCopy
            onClick={copyUrl}
            copied={copiedUrl}
            copiedLabel={t("copied")}
            defaultLabel={t("copy")}
          />
        </div>
      </div>

      {/* ── JSON config snippet ───────────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2">
            <FileJson size={13} strokeWidth={2} aria-hidden className="text-foreground-tertiary" />
            <span className="text-[11px] font-medium uppercase tracking-wide text-foreground-tertiary">
              {t("jsonSnippetTitle")}
            </span>
          </div>
          <InlineCopy
            onClick={copyJson}
            copied={copiedJson}
            copiedLabel={t("jsonCopied")}
            defaultLabel={t("copyJson")}
          />
        </div>
        <pre className="overflow-x-auto rounded-xl bg-background-inverse px-4 py-3.5 font-mono text-[12px] leading-relaxed text-white/85">
          <code>{jsonConfig}</code>
        </pre>
      </div>
    </section>
  );
}
