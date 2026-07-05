import { create } from "zustand";
import { persist } from "zustand/middleware";

/** A selected scope entry (knowledge base, document or tag). */
export interface ScopeRef {
  /** Underlying id: kb_name / document_id / tag keyword. */
  id: string;
  /** Human-readable label shown on chips and lists. */
  label: string;
  /** Optional secondary line (e.g. "6 KBs · 12 docs"). */
  meta?: string;
}

/** The three scope dimensions, combined as a union (OR) at query time. */
export interface ScopeSelectionState {
  kbNames: ScopeRef[];
  documents: ScopeRef[];
  tags: ScopeRef[];
}

/** Query-payload shape (matches the backend ``ScopeSelection``). */
export interface ScopeFilterPayload {
  kb_names: string[];
  document_ids: string[];
  tags: string[];
}

type ScopeKind = "kb" | "document" | "tag";

interface ScopeState extends ScopeSelectionState {
  /** Replace the whole selection (used by drawer Apply and session hydrate). */
  setScope: (next: ScopeSelectionState) => void;
  /** Add a document (used by @ mention); dedups by id. */
  addDocument: (ref: ScopeRef) => void;
  /** Remove a single entry from a dimension. */
  removeItem: (kind: ScopeKind, id: string) => void;
  /** Clear every dimension. */
  clear: () => void;
}

const EMPTY: ScopeSelectionState = { kbNames: [], documents: [], tags: [] };

export const useScopeStore = create<ScopeState>()(
  persist(
    (set) => ({
      ...EMPTY,
      setScope: (next) =>
        set({
          kbNames: next.kbNames,
          documents: next.documents,
          tags: next.tags,
        }),
      addDocument: (ref) =>
        set((state) =>
          state.documents.some((d) => d.id === ref.id)
            ? state
            : { documents: [...state.documents, ref] },
        ),
      removeItem: (kind, id) =>
        set((state) => {
          if (kind === "kb") return { kbNames: state.kbNames.filter((k) => k.id !== id) };
          if (kind === "document") return { documents: state.documents.filter((d) => d.id !== id) };
          return { tags: state.tags.filter((tag) => tag.id !== id) };
        }),
      clear: () => set({ ...EMPTY }),
    }),
    { name: "eagle-rag-scope" },
  ),
);

/** Total number of selected scope entries across all dimensions. */
export function scopeCount(s: ScopeSelectionState): number {
  return s.kbNames.length + s.documents.length + s.tags.length;
}

/** Build the ``scope_filter`` query payload, or ``null`` when nothing is selected. */
export function toScopeFilter(s: ScopeSelectionState): ScopeFilterPayload | null {
  if (scopeCount(s) === 0) return null;
  return {
    kb_names: s.kbNames.map((k) => k.id),
    document_ids: s.documents.map((d) => d.id),
    tags: s.tags.map((tag) => tag.id),
  };
}

/**
 * Scope kwargs for ``/query`` and ``/search``.
 *
 * The scope drawer is authoritative on the QA page; do not fall back to the
 * global ingest KB picker (`useKBStore`) when the user leaves scope at "All".
 */
export function toQueryScope(s: ScopeSelectionState): {
  scope_filter: ScopeFilterPayload | null;
  kb_name: null;
} {
  return { scope_filter: toScopeFilter(s), kb_name: null };
}
