import { previewContentUrl } from "@/components/document-preview/preview-urls";
import { resolveRenderer } from "@/components/document-preview/resolve-renderer";
import type { PreviewTarget } from "@/components/document-preview/types";
import { attachmentContentUrl } from "@/lib/hooks/useAttachments";
import { prefetchPreviewResource } from "@/lib/hooks/usePreviewResource";
import { useImageLightboxStore } from "@/lib/stores/imageLightboxStore";
import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";

interface PreviewState {
  modalTarget: PreviewTarget | null;
  openPreview: (target: PreviewTarget, queryClient?: QueryClient) => void;
  closePreview: () => void;
}

function openImageTarget(target: PreviewTarget): boolean {
  const openImageLightbox = useImageLightboxStore.getState().openImageLightbox;

  if (target.kind === "image") {
    openImageLightbox({ kind: "image", imageId: target.imageId });
    return true;
  }

  if (target.kind === "attachment") {
    openImageLightbox({
      kind: "url",
      src: target.previewUrl ?? attachmentContentUrl(target.attachmentId),
      alt: target.title,
    });
    return true;
  }

  if (target.kind === "file" && resolveRenderer(target) === "image") {
    const src = previewContentUrl(target);
    if (src) {
      openImageLightbox({ kind: "url", src, alt: target.title });
      return true;
    }
  }

  return false;
}

export const usePreviewStore = create<PreviewState>((set) => ({
  modalTarget: null,
  openPreview: (target, queryClient) => {
    if (openImageTarget(target)) return;
    if (queryClient) prefetchPreviewResource(queryClient, target);
    set({ modalTarget: target });
  },
  closePreview: () => set({ modalTarget: null }),
}));
