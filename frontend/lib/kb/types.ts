/** Shared knowledge-base domain types and display helpers (no mock data). */

export type KBStatus = "online" | "offline" | "degraded";

export type KBTheme = "blue" | "violet" | "emerald" | "indigo" | "amber" | "teal" | "rose" | "sky";

export type KBIconKey =
  | "landmark"
  | "scroll"
  | "pill"
  | "scale"
  | "receipt"
  | "clipboard"
  | "book"
  | "file";

export interface KnowledgeBase {
  kbName: string;
  displayName: string;
  description: string;
  theme: KBTheme;
  icon: KBIconKey;
  documents: number;
  graphNodes: number;
  visualSlices: number;
  queries7d: number;
  activeIngestions: number;
  pdfTextPageRatio: number;
  collections: string[];
  /** Runtime status returned by the detail endpoint. */
  status?: KBStatus;
  /** Millisecond offset from now, derived from the API `updated_at`. */
  updatedAgoMs: number;
  recent: boolean;
}

export type KBSort = "recent" | "name" | "size";

export interface KBOverview {
  kbCount: number;
  activeIngestions: number;
  totalDocuments: number;
  totalGraphNodes: number;
  totalVectors: number;
}

/** Chart: document format distribution slice (label from API). */
export interface FormatSegment {
  key?: string;
  label: string;
  value: number;
  color: string;
}

/** Chart: 7-day ingestion volume bar (label from API). */
export interface VolumePoint {
  label: string;
  value: number;
}

export type PipelineKind = "knowhere" | "pixelrag";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** Relative time formatter (zh/en) for card "updated X ago" labels. */
export function formatRelative(agoMs: number, locale: string): string {
  const rtf = new Intl.RelativeTimeFormat(locale === "en" ? "en" : "zh", { numeric: "auto" });
  const abs = Math.abs(agoMs);
  if (abs < HOUR) return rtf.format(-Math.round(agoMs / MIN), "minute");
  if (abs < DAY) return rtf.format(-Math.round(agoMs / HOUR), "hour");
  if (abs < 30 * DAY) return rtf.format(-Math.round(agoMs / DAY), "day");
  return rtf.format(-Math.round(agoMs / (30 * DAY)), "month");
}
