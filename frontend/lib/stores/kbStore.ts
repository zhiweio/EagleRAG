import { create } from "zustand";
import { persist } from "zustand/middleware";

interface KBState {
  /** Currently selected knowledge-base id. "" or null means use the system default. */
  kbName: string;
  setKbName: (name: string) => void;
}

export const useKBStore = create<KBState>()(
  persist(
    (set) => ({
      kbName: "",
      setKbName: (name) => set({ kbName: name }),
    }),
    { name: "eagle-rag-kb" },
  ),
);
