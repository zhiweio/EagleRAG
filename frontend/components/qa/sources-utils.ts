import { API_BASE, imageUrl } from "@/lib/api/client";
import type { QuerySources } from "@/lib/types";
import type { FlatSource } from "./types";

/**
 * Flatten a message's `sources` into a single ordered list with 1-based indices.
 * Text sources come first, then image sources, mirroring the backend's
 * `{"text": [...], "image": [...]}` shape so that answer citations `[n]` line
 * up with the n-th card rendered in the evidence rail.
 */
export function flattenSources(sources: QuerySources | null | undefined): FlatSource[] {
  if (!sources) return [];
  const out: FlatSource[] = [];
  let idx = 1;
  for (const s of sources.text ?? []) {
    out.push({ index: idx, type: "text", source: s });
    idx += 1;
  }
  for (const s of sources.image ?? []) {
    out.push({ index: idx, type: "image", source: s });
    idx += 1;
  }
  return out;
}

/** Find the 1-based flat source index for a visual `image_id`, if present. */
export function findImageSourceIndex(
  sources: QuerySources | null | undefined,
  imageId: string,
): number | null {
  if (!imageId) return null;
  const flat = flattenSources(sources);
  return (
    flat.find((f) => f.type === "image" && sourceString(f.source, "image_id") === imageId)?.index ??
    null
  );
}

/** Safely coerce an unknown source field to a trimmed string, or "" if absent. */
export function sourceString(source: Record<string, unknown>, key: string): string {
  const v = source[key];
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return "";
}

/** Format a relevance score (0..1 or raw float) as a compact percentage. */
export function formatScore(source: Record<string, unknown>): string {
  const raw = source.score;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    if (raw <= 1) return `${Math.round(raw * 100)}%`;
    return raw.toFixed(2);
  }
  return "";
}

/** Format a relevance score (0..1 or raw float) as a compact `sim 0.91` label. */
export function formatSim(source: Record<string, unknown>): string {
  const raw = source.score;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw <= 1 ? raw.toFixed(2) : raw.toFixed(2);
  }
  return "";
}

/** Best-effort display file name for a source (attachment name, path leaf…). */
export function sourceFileName(source: Record<string, unknown>): string {
  const explicit =
    sourceString(source, "file_name") ||
    sourceString(source, "document_name") ||
    sourceString(source, "name");
  if (explicit) return explicit;
  const path = sourceString(source, "path");
  if (path) {
    const leaf = path.split(/[\\/›>]/).pop();
    if (leaf) return leaf.trim();
  }
  return sourceString(source, "document_id") || "";
}

/** Strip common Knowhere OCR prefixes before rendering visual summaries. */
export function normalizeVisualSummary(summary: string): string {
  return summary.replace(/^image-\d+\s+/i, "").trim();
}

/** Parse a title line from Knowhere visual `content_summary` markdown. */
export function parseVisualSummaryTitle(summary: string): string {
  const normalized = normalizeVisualSummary(summary);
  const match = normalized.match(/\*\*Title:\*\*\s*([^*\n]+)/i);
  return match?.[1]?.trim() ?? "";
}

/** Human-readable label for a visual source citation card / list row. */
export function sourceVisualTitle(source: Record<string, unknown>): string {
  const fileName = sourceFileName(source);
  const docId = sourceDocumentId(source);
  if (fileName && fileName !== docId) return fileName;

  const titled = parseVisualSummaryTitle(sourceString(source, "content_summary"));
  if (titled) return titled;

  const parent = sourceString(source, "parent_section");
  if (parent) {
    const leaf = parent
      .split(/[\\/›>]/)
      .pop()
      ?.trim();
    if (leaf) return leaf;
  }

  const imageId = sourceString(source, "image_id");
  if (imageId) {
    const tail = imageId.match(/_vc_\d+_\d+$/)?.[0]?.slice(1);
    if (tail) return tail;
    return imageId.length > 28 ? `${imageId.slice(0, 12)}…` : imageId;
  }

  return docId || "";
}

/** Excerpt body for inline citation hovercards. */
export function sourceCitationExcerpt(item: FlatSource): string {
  if (item.type === "image") {
    let body = normalizeVisualSummary(sourceString(item.source, "content_summary"));
    const title = parseVisualSummaryTitle(body);
    if (title) {
      body = body.replace(/\*\*Title:\*\*\s*[^*\n]+\s*/i, "").trim();
    }
    return body;
  }
  return sourceExcerpt(item.source);
}

/** Title line for inline citation hovercards. */
export function sourceCitationTitle(item: FlatSource, fallbackIndex: number): string {
  if (item.type === "image") {
    return sourceVisualTitle(item.source) || `#${fallbackIndex}`;
  }
  return sourceFileName(item.source) || `#${fallbackIndex}`;
}

/** Break a source `path`/`level` into breadcrumb segments for display. */
export function sourceCrumbs(source: Record<string, unknown>): string[] {
  const path = sourceString(source, "path") || sourceString(source, "level");
  if (!path) return [];
  return path
    .split(/\s*[\\/›>]\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** First non-empty text-like field for an excerpt preview. */
export function sourceExcerpt(source: Record<string, unknown>): string {
  return (
    sourceString(source, "content") ||
    sourceString(source, "text") ||
    sourceString(source, "snippet") ||
    sourceString(source, "excerpt") ||
    sourceString(source, "summary")
  );
}

/** The owning document id of a source, or "" when absent. */
export function sourceDocumentId(source: Record<string, unknown>): string {
  return sourceString(source, "document_id");
}

/** Keyword tags attached to a source chunk (Knowhere `keywords`). */
export function sourceKeywords(source: Record<string, unknown>): string[] {
  const raw = source.keywords;
  if (!Array.isArray(raw)) return [];
  return raw.map((k) => String(k).trim()).filter(Boolean);
}

/** Compact page label from `page_nums` (list) or a single `page` field. */
export function sourcePageLabel(source: Record<string, unknown>): string {
  const nums = source.page_nums;
  if (Array.isArray(nums) && nums.length > 0) {
    const pages = nums.map((n) => String(n)).filter(Boolean);
    if (pages.length === 1) return `p.${pages[0]}`;
    if (pages.length > 1) return `p.${pages[0]}–${pages[pages.length - 1]}`;
  }
  const single = sourceString(source, "page");
  return single ? `p.${single}` : "";
}

/** Normalized chunk kind: `text` | `table` | `image` | `section_summary` | `tile`. */
export function sourceChunkType(source: Record<string, unknown>): string {
  return sourceString(source, "chunk_type") || sourceString(source, "type") || "text";
}

/**
 * Resolve an inline answer image `src` for Streamdown rendering.
 *
 * VLMs often emit Markdown images with hallucinated external URLs. When the
 * message already has retrieved visual sources, remap those URLs to the API
 * image byte-stream (`/images/{image_id}`) the evidence rail uses.
 */
export function resolveAnswerImageSrc(
  src: string | undefined,
  alt: string | undefined,
  flat: FlatSource[],
): string | undefined {
  if (!src?.trim()) return undefined;
  const normalized = src.trim();
  if (normalized.startsWith("data:")) return normalized;
  if (normalized.startsWith(API_BASE)) return normalized;
  if (normalized.startsWith("/images/")) return `${API_BASE}${normalized}`;

  const visuals = flat.filter((f) => f.type === "image");
  const isExternalHttp = /^https?:\/\//i.test(normalized) && !normalized.startsWith(API_BASE);
  if (!isExternalHttp || visuals.length === 0) return normalized;

  const altLower = (alt ?? "").toLowerCase();
  if (altLower) {
    const matched = visuals.find((v) => {
      const summary = (sourceString(v.source, "content_summary") ?? "").toLowerCase();
      if (summary.includes(altLower)) return true;
      return altLower
        .split(/\s+/)
        .filter((w) => w.length > 3)
        .some((w) => summary.includes(w));
    });
    if (matched) {
      const id = sourceString(matched.source, "image_id");
      if (id) return imageUrl(id);
    }
  }

  const preferred = visuals.find((v) => sourceChunkType(v.source) === "image") ?? visuals[0];
  const imageId = sourceString(preferred.source, "image_id");
  return imageId ? imageUrl(imageId) : undefined;
}
