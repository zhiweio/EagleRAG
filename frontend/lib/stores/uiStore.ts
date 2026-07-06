import { create } from "zustand";

interface UIState {
  /** Whether the global document search modal is open. */
  globalSearchOpen: boolean;
  setGlobalSearchOpen: (open: boolean) => void;

  /** Whether the QA page history drawer is open. */
  qaHistoryOpen: boolean;
  setQaHistoryOpen: (open: boolean) => void;

  /** Job id for the ingest page task-log modal (null means closed). */
  ingestLogsJobId: string | null;
  setIngestLogsJobId: (id: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  globalSearchOpen: false,
  setGlobalSearchOpen: (open) => set({ globalSearchOpen: open }),

  qaHistoryOpen: false,
  setQaHistoryOpen: (open) => set({ qaHistoryOpen: open }),

  ingestLogsJobId: null,
  setIngestLogsJobId: (id) => set({ ingestLogsJobId: id }),
}));
