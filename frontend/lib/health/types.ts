/**
 * Type definitions for the "MCP & Service Health" module (module 3).
 *
 * Components import types from this file; live data is fetched via the hooks in
 * `@/lib/hooks/useHealth` (which call the backend `/health` + `/admin/*` APIs).
 *
 * Labels (tab names, table headers, section titles, buttons) are localised via
 * next-intl. The values produced by hooks are technical content that may be
 * transcribed verbatim from the design frames and are intentionally
 * language-neutral.
 */

import type { LucideIcon } from "lucide-react";

/**
 * Service status shown on a card / drawer.
 *
 * - ``online``  ← backend ``DependencyStatus="up"``: service healthy, green.
 * - ``offline`` ← backend ``"down"``: service faulty or unreachable, red.
 * - ``unknown`` ← backend ``"unknown"``: not probed actively (e.g. VLM calls are costly) /
 *   optional dependency not enabled (e.g. pixelrag vision extra), **not a failure**. Neutral grey, distinct from degraded.
 * - ``degraded`` ← only used on multi-dependency aggregate cards (e.g. storage=minio+redis, any one down).
 */
export type ServiceStatus = "online" | "degraded" | "offline" | "unknown";
export type IconTone = "accent" | "success" | "warning" | "danger" | "purple";
export type ServiceKind = "storage" | "knowhere" | "celery" | "milvus" | "pixelrag" | "models";
export type DrawerKind = "celery" | "milvus" | "vlm" | "mcp" | "knowhere" | "storage";

/** A metric chip rendered on a service card. */
export interface ServiceChip {
  label: string;
  tone: "accent" | "success" | "warning";
}

/** A card in the main service grid (frame 03). */
export interface ServiceCardData {
  kind: ServiceKind;
  /** i18n key suffix under `health.serviceCards.*` for name + description. */
  i18nKey: string;
  /** Optional nested variant (e.g. knowhere `api` / `parser`). */
  i18nVariant?: string;
  icon: LucideIcon;
  tone: IconTone;
  status: ServiceStatus;
  chips: ServiceChip[];
  uptime: string;
  /** Which drawer this card opens (null = no drawer). */
  drawer: DrawerKind | null;
}

/** Drawer header meta (icon + tone). The status pill is driven separately by ``ServiceDrawer``. */
export interface DrawerMeta {
  icon: LucideIcon;
  tone: IconTone;
}

/** A single point in the celery queue backlog chart (frame 04). */
export interface QueuePoint {
  time: string;
  knowhere: number;
  pixelrag: number;
}

/** A row in the celery worker table (frame 04). */
export interface WorkerRow {
  name: string;
  pid: string;
  state: "busy" | "idle";
  current: string;
  memory: string;
}

/** A field cell in a milvus/knowhere collection row. */
export interface CollectionField {
  /** i18n key under `health.milvusDrawer.fieldLabels.*` */
  labelKey: "dim" | "metric" | "index";
  value: string;
}

/** A row in the milvus/knowhere collection table (frames 05 / 13). */
export interface CollectionRow {
  name: string;
  /** i18n key under `health.*Drawer.tag.*` */
  tagKey: "visual" | "text" | "patent" | "finance" | "kb" | "storage";
  count: string;
  fields: CollectionField[];
  meta: string;
}

/** A row in the VLM/LLM model router table (frame 06). */
export interface ModelRouterRowData {
  /** i18n key under `health.vlmDrawer.models.*` */
  key: "vlm" | "textLlm" | "embedding";
  name: string;
  enabled: boolean;
}

/** A row in the MCP tools table (frame 07). */
export interface McpToolData {
  name: string;
  /** i18n key under `health.mcpDrawer.tools.*` for description. */
  descKey: "query" | "trace" | "read";
  params: string;
}

/** Log severity levels for the live logs tab (frame 08). */
export type LogLevel = "INFO" | "DEBUG" | "WARN" | "ERROR";

/** A single log line in the live logs / MCP console (frames 07 / 08). */
export interface LogLine {
  time: string;
  level: LogLevel;
  source: string;
  message: string;
}

/** A row in the container-style probes table (frame 12). */
export interface ProbeRowData {
  /** i18n key under `health.configProbes.probes.*` */
  key: "liveness" | "readiness" | "startup";
  timing: string;
  status: "pass" | "degraded";
}

/** A row in the resource limits table (frame 12). */
export interface ResourceLimitData {
  /** i18n key under `health.configProbes.resources.*` */
  key: "cpu" | "memory";
  used: string;
  limit: string;
  unit: string;
  percent: number;
}
