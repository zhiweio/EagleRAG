import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Ingest page task filter conditions. */
interface TaskFilter {
  query: string;
  pipelines: string[];
  statuses: string[];
  autoPoll: boolean;
}

/** Document filter conditions (QA page Scope Filter and future document management). */
interface DocumentFilter {
  sourceType: string | null;
  pipeline: string | null;
  year: number | null;
}

interface FilterState {
  taskFilter: TaskFilter;
  documentFilter: DocumentFilter;
  setTaskFilter: <K extends keyof TaskFilter>(key: K, value: TaskFilter[K]) => void;
  setDocumentFilter: <K extends keyof DocumentFilter>(key: K, value: DocumentFilter[K]) => void;
  clearTaskFilter: () => void;
  clearDocumentFilter: () => void;
}

export const useFilterStore = create<FilterState>()(
  persist(
    (set) => ({
      taskFilter: {
        query: "",
        pipelines: [],
        statuses: [],
        autoPoll: true,
      },
      documentFilter: {
        sourceType: null,
        pipeline: null,
        year: null,
      },
      setTaskFilter: (key, value) =>
        set((state) => ({ taskFilter: { ...state.taskFilter, [key]: value } })),
      setDocumentFilter: (key, value) =>
        set((state) => ({ documentFilter: { ...state.documentFilter, [key]: value } })),
      clearTaskFilter: () =>
        set({
          taskFilter: { query: "", pipelines: [], statuses: [], autoPoll: true },
        }),
      clearDocumentFilter: () =>
        set({
          documentFilter: { sourceType: null, pipeline: null, year: null },
        }),
    }),
    { name: "eagle-rag-filter" },
  ),
);
