import type { PreviewTarget } from "@/components/document-preview/types";

/** Stable React Query cache key for a preview target, or null when no remote fetch is needed. */
export function previewCacheKey(target: PreviewTarget): string | null {
  switch (target.kind) {
    case "file":
      return `file:${target.documentId}`;
    case "table":
      if (target.html) return null;
      return target.chunkId ? `table:${target.documentId}:${target.chunkId}` : null;
    case "attachment":
      return `attachment:${target.attachmentId}`;
    case "image":
      return `image:${target.imageId}`;
    default:
      return null;
  }
}
