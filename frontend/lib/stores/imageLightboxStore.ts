import { create } from "zustand";

/** Image shown in the fullscreen lightbox (KB visual tile or inline URL). */
export type ImageLightboxTarget =
  | { kind: "image"; imageId: string }
  | { kind: "url"; src: string; alt?: string };

interface ImageLightboxState {
  target: ImageLightboxTarget | null;
  openImageLightbox: (target: ImageLightboxTarget) => void;
  closeImageLightbox: () => void;
}

export const useImageLightboxStore = create<ImageLightboxState>((set) => ({
  target: null,
  openImageLightbox: (target) => set({ target }),
  closeImageLightbox: () => set({ target: null }),
}));
