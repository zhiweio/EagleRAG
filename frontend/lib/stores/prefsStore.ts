import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * prefsStore — browser-side app preferences persisted to localStorage.
 * Stores settings unrelated to backend accounts that only affect local UI
 * behavior (e.g. sidebar collapse state).
 */
interface PrefsState {
  /** Whether the sidebar is collapsed (icons-only when collapsed). */
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
}

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: "eagle-rag-prefs" },
  ),
);
