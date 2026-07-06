import { chunkHtmlUrl, fileUrl, imageUrl } from "@/lib/api/client";
import { attachmentContentUrl } from "@/lib/hooks/useAttachments";
import type { PreviewTarget } from "./types";

/** Resolve a fetchable URL for the preview target, when applicable. */
export function previewContentUrl(target: PreviewTarget): string | undefined {
  switch (target.kind) {
    case "image":
      return imageUrl(target.imageId);
    case "table":
      return target.chunkId ? chunkHtmlUrl(target.documentId, target.chunkId) : undefined;
    case "file":
      return fileUrl(target.documentId);
    case "attachment":
      return target.previewUrl ?? attachmentContentUrl(target.attachmentId);
    default:
      return undefined;
  }
}

/** Human-readable title for chrome and download filenames. */
export function previewTitle(target: PreviewTarget): string {
  switch (target.kind) {
    case "image":
      return target.title ?? target.imageId;
    case "table":
      return target.title ?? target.chunkId ?? target.documentId;
    case "file":
      return target.title ?? target.documentId;
    case "attachment":
      return target.title ?? target.attachmentId;
    default:
      return "preview";
  }
}
