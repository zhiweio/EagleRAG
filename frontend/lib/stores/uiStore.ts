import { create } from "zustand";

interface UIState {
  /** Whether the QA page history drawer is open. */
  qaHistoryOpen: boolean;
  setQaHistoryOpen: (open: boolean) => void;

  /** Image id for the QA page image lightbox (null means closed). */
  qaLightboxImageId: string | null;
  setQaLightboxImageId: (id: string | null) => void;

  /** Job id for the ingest page task-log modal (null means closed). */
  ingestLogsJobId: string | null;
  setIngestLogsJobId: (id: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  qaHistoryOpen: false,
  setQaHistoryOpen: (open) => set({ qaHistoryOpen: open }),

  qaLightboxImageId: null,
  setQaLightboxImageId: (id) => set({ qaLightboxImageId: id }),

  ingestLogsJobId: null,
  setIngestLogsJobId: (id) => set({ ingestLogsJobId: id }),
}));
