"use client";

import type { KBIconKey, KBStatus, KBTheme, PipelineKind } from "@/lib/kb/types";

export type { PipelineKind };
import {
  BookOpen,
  ClipboardCheck,
  File,
  FileChartColumn,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Globe,
  Landmark,
  Pill,
  Presentation,
  Receipt,
  Scale,
  ScrollText,
} from "lucide-react";
import type { ComponentType, SVGProps } from "react";

/**
 * Knowledge base theme colours (icon colour + soft fill). Taken from the design
 * frame KB Card / Create KB palette. Applied via inline style to avoid Tailwind
 * dynamic class names being purged.
 */
export const THEME_STYLES: Record<KBTheme, { color: string; soft: string }> = {
  blue: { color: "#0485F7", soft: "#0485F726" },
  violet: { color: "#7C3AED", soft: "#EDE9FE" },
  emerald: { color: "#059669", soft: "#D1FAE5" },
  indigo: { color: "#4F46E5", soft: "#E0E7FF" },
  amber: { color: "#D97706", soft: "#FEF3C7" },
  teal: { color: "#0D9488", soft: "#CCFBF1" },
  rose: { color: "#E11D48", soft: "#FFE4E6" },
  sky: { color: "#0284C7", soft: "#E0F2FE" },
};

/** The design uses lucide icons. */
const ICONS: Record<KBIconKey, ComponentType<SVGProps<SVGSVGElement>>> = {
  landmark: Landmark,
  scroll: ScrollText,
  pill: Pill,
  scale: Scale,
  receipt: Receipt,
  clipboard: ClipboardCheck,
  book: BookOpen,
  file: File,
};

export const ICON_ORDER: KBIconKey[] = ["landmark", "scroll", "pill", "receipt", "book", "scale"];

export function KBIcon({
  icon,
  className,
  style,
}: {
  icon: KBIconKey;
  className?: string;
  style?: SVGProps<SVGSVGElement>["style"];
}) {
  const Cmp = ICONS[icon] ?? ScrollText;
  return <Cmp className={className} style={style} aria-hidden />;
}

/** Knowledge-base theme badge: soft rounded square + theme-color icon. */
export function KBBadge({
  theme,
  icon,
  size = 44,
  iconSize = 22,
  radius = 8,
}: {
  theme: KBTheme;
  icon: KBIconKey;
  size?: number;
  iconSize?: number;
  radius?: number;
}) {
  const style = THEME_STYLES[theme];
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size, backgroundColor: style.soft, borderRadius: radius }}
    >
      <KBIcon icon={icon} style={{ width: iconSize, height: iconSize, color: style.color }} />
    </span>
  );
}

/** Pipeline tag styles (Knowhere blue / PixelRAG purple). */
export const PIPELINE_STYLES: Record<PipelineKind, { label: string; color: string; soft: string }> =
  {
    knowhere: { label: "Knowhere", color: "#1D4ED8", soft: "#DBEAFE" },
    pixelrag: { label: "PixelRAG", color: "#7E22CE", soft: "#F3E8FF" },
  };

/** Pipeline pill (design frame 10 doc table / detail dashboard). */
export function PipelineTag({ kind }: { kind: PipelineKind }) {
  const s = PIPELINE_STYLES[kind];
  return (
    <span
      className="inline-flex w-fit items-center rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={{ backgroundColor: s.soft, color: s.color }}
    >
      {s.label}
    </span>
  );
}

/** Underlying Collection pill (eagle_text blue / eagle_visual purple; data-driven colors). */
export function CollectionTag({ name }: { name: string }) {
  const visual = name === "eagle_visual";
  return (
    <span
      className={`inline-flex w-fit items-center rounded-full px-[9px] py-1 font-mono text-[11px] font-medium ${
        visual ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"
      }`}
    >
      {name}
    </span>
  );
}

/** Runtime status styles (online/offline/degraded) — used for the detail dashboard engine status pill. */
export const STATUS_STYLES: Record<KBStatus, { dot: string; bg: string; fg: string }> = {
  online: { dot: "#17C964", bg: "#17C96426", fg: "#12A150" },
  offline: { dot: "#FF383C", bg: "#FF383C26", fg: "#E11D48" },
  degraded: { dot: "#F5A524", bg: "#F5A52426", fg: "#B45309" },
};

/* ============================================================
 * Document-list visuals: file-format badges + status dots (no emoji).
 * ============================================================ */

/** Lucide icon component type for file-format badges. */
type FileIcon = ComponentType<SVGProps<SVGSVGElement>>;

/** Format-code badge colored by file extension, with a matching Lucide icon. */
const FILE_FORMAT_STYLES: Record<string, { icon: FileIcon; color: string; soft: string }> = {
  pdf: { icon: FileText, color: "#DC2626", soft: "#FEE2E2" },
  doc: { icon: FileText, color: "#2563EB", soft: "#DBEAFE" },
  docx: { icon: FileText, color: "#2563EB", soft: "#DBEAFE" },
  xls: { icon: FileSpreadsheet, color: "#059669", soft: "#D1FAE5" },
  xlsx: { icon: FileSpreadsheet, color: "#059669", soft: "#D1FAE5" },
  csv: { icon: FileChartColumn, color: "#059669", soft: "#D1FAE5" },
  html: { icon: FileCode, color: "#EA580C", soft: "#FFEDD5" },
  htm: { icon: FileCode, color: "#EA580C", soft: "#FFEDD5" },
  md: { icon: FileText, color: "#7C3AED", soft: "#EDE9FE" },
  markdown: { icon: FileText, color: "#7C3AED", soft: "#EDE9FE" },
  txt: { icon: FileType, color: "#71717A", soft: "#E4E4E7" },
  json: { icon: FileCode, color: "#D97706", soft: "#FEF3C7" },
  xml: { icon: FileCode, color: "#0891B2", soft: "#CFFAFE" },
  ppt: { icon: Presentation, color: "#DC2626", soft: "#FEE2E2" },
  pptx: { icon: Presentation, color: "#DC2626", soft: "#FEE2E2" },
  png: { icon: FileImage, color: "#7C3AED", soft: "#EDE9FE" },
  jpg: { icon: FileImage, color: "#7C3AED", soft: "#EDE9FE" },
  jpeg: { icon: FileImage, color: "#7C3AED", soft: "#EDE9FE" },
  gif: { icon: FileImage, color: "#7C3AED", soft: "#EDE9FE" },
  webp: { icon: FileImage, color: "#7C3AED", soft: "#EDE9FE" },
};

/** HTTP(S) web page / URL resource (no file extension in path). */
const URL_RESOURCE_STYLE = { icon: Globe, color: "#0284C7", soft: "#E0F2FE" };

export function isHttpUri(value: string | undefined | null): boolean {
  if (!value) return false;
  const lower = value.trim().toLowerCase();
  return lower.startsWith("http://") || lower.startsWith("https://");
}

function pathExtension(value: string): string {
  const base = value.split(/[?#]/)[0] ?? value;
  const segment = base.split(/[/\\]/).pop() ?? base;
  const idx = segment.lastIndexOf(".");
  return idx >= 0 ? segment.slice(idx + 1).toLowerCase() : "";
}

/** Format-distribution segment key → representative filename for badge icons. */
export const FORMAT_KEY_FILENAMES: Record<string, string> = {
  pdf_text: "document.pdf",
  pdf_scan: "scan.pdf",
  docx: "document.docx",
  pptx: "slides.pptx",
  xlsx: "data.xlsx",
  csv: "data.csv",
  md: "notes.md",
  txt: "readme.txt",
  json: "config.json",
  web: "page.html",
  image: "photo.png",
  other: "file.bin",
};

export function fileFormatFromKey(key: string) {
  return fileFormatFromName(FORMAT_KEY_FILENAMES[key] ?? "file.bin");
}

export function resolveFileFormat(opts: {
  name: string;
  sourceUri?: string | null;
}): { icon: FileIcon; color: string; soft: string } {
  const candidates = [opts.sourceUri, opts.name].filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0,
  );
  for (const candidate of candidates) {
    if (!isHttpUri(candidate)) continue;
    const ext = pathExtension(candidate);
    if (ext && FILE_FORMAT_STYLES[ext]) {
      return FILE_FORMAT_STYLES[ext];
    }
    return URL_RESOURCE_STYLE;
  }
  return fileFormatFromName(opts.name);
}

export function fileFormatFromName(name: string) {
  if (isHttpUri(name)) {
    const ext = pathExtension(name);
    if (ext && FILE_FORMAT_STYLES[ext]) {
      return FILE_FORMAT_STYLES[ext];
    }
    return URL_RESOURCE_STYLE;
  }
  // Reject non-filename inputs (UUIDs, bare IDs) — these have no usable
  // extension, so fall back to a neutral File icon instead of showing the
  // first 4 characters of the id (e.g. "3770" for a UUID).
  const hasDot = name.includes(".");
  const ext = hasDot ? (name.split(".").pop() ?? "").toLowerCase() : "";
  return (
    FILE_FORMAT_STYLES[ext] ?? {
      icon: File,
      color: "#71717A",
      soft: "#E4E4E7",
    }
  );
}

/** File-format badge: soft rounded square + colored Lucide icon.
 *
 * When ``forceIcon`` is provided, it overrides the extension-derived icon —
 * used for dispatched sub-tasks (e.g. PixelRAG visual pipeline) whose
 * document name is an ID rather than a real filename.
 */
export function FileBadge({
  name,
  sourceUri,
  size = 38,
  forceIcon,
}: {
  name: string;
  sourceUri?: string | null;
  size?: number;
  forceIcon?: FileIcon;
}) {
  const f = resolveFileFormat({ name, sourceUri });
  const Icon = forceIcon ?? f.icon;
  const iconSize = Math.round(size * 0.5);
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-[10px]"
      style={{
        width: size,
        height: size,
        backgroundColor: f.soft,
        color: f.color,
      }}
      aria-hidden
    >
      <Icon width={iconSize} height={iconSize} strokeWidth={2} />
    </span>
  );
}

/** Normalized key for a document's runtime status. */
export type DocStatusKey = "ready" | "active" | "failed" | "idle";

export function docStatusKey(status: string): DocStatusKey {
  const s = (status ?? "").toLowerCase();
  if (/(ready|done|complete|success|ok|indexed)/.test(s)) return "ready";
  if (/(process|run|pending|ingest|queue|progress|started)/.test(s)) return "active";
  if (/(fail|error|abort|cancel)/.test(s)) return "failed";
  return "idle";
}

export const DOC_STATUS_STYLES: Record<DocStatusKey, { color: string }> = {
  ready: { color: "#17C964" },
  active: { color: "#F5A524" },
  failed: { color: "#FF383C" },
  idle: { color: "#A1A1AA" },
};

/** Document status indicator dot (active state has a breathing animation). */
export function DocStatusDot({ status }: { status: string }) {
  const k = docStatusKey(status);
  const s = DOC_STATUS_STYLES[k];
  return (
    <span className="relative flex h-2 w-2" aria-hidden>
      {k === "active" ? (
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ backgroundColor: s.color }}
        />
      ) : null}
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: s.color }}
      />
    </span>
  );
}
