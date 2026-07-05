import { API_BASE } from "@/lib/api/client";
import {
  deleteAttachmentAttachmentsAttachmentIdDelete,
  uploadAttachmentAttachmentsPost,
} from "@/lib/api/generated/sdk.gen";

export const MAX_IMAGE_ATTACHMENT_BYTES = 5 * 1024 * 1024;

/** Public URL for rendering a persisted session attachment. */
export function attachmentContentUrl(attachmentId: string): string {
  return `${API_BASE}/attachments/${encodeURIComponent(attachmentId)}/content`;
}

export async function uploadAttachment(
  file: File,
  sessionId?: string,
): Promise<{ attachment_id: string }> {
  const result = await uploadAttachmentAttachmentsPost({
    body: {
      file,
      session_id: sessionId ?? undefined,
    },
  });
  if (result.error) {
    const detail =
      typeof result.error === "object" && result.error && "detail" in result.error
        ? String((result.error as { detail: unknown }).detail)
        : `upload failed ${result.response?.status ?? ""}`;
    throw new Error(detail);
  }
  const data = result.data as { attachment_id?: string };
  if (!data.attachment_id) throw new Error("upload response missing attachment_id");
  return { attachment_id: data.attachment_id };
}

export async function deleteAttachment(attachmentId: string): Promise<void> {
  const result = await deleteAttachmentAttachmentsAttachmentIdDelete({
    path: { attachment_id: attachmentId },
  });
  if (result.error) {
    throw new Error("delete attachment failed");
  }
}
