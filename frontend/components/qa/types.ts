import type { QuerySources, RouteInfo, Step } from "@/lib/types";

/** Retrieval mode passed to the /query and /search endpoints. */
export type Mode = "auto" | "text" | "visual" | "hybrid";

export const MODE_OPTIONS: Mode[] = ["auto", "text", "visual", "hybrid"];

/**
 * Interaction mode of the composer:
 * - `ask` streams a generated answer (`/query/stream`);
 * - `search` streams pure retrieval (`/search/stream`);
 * - `search` runs pure retrieval (`/search`) and renders sources only.
 */
export type AskMode = "ask" | "search";

export const ASK_MODE_OPTIONS: AskMode[] = ["ask", "search"];

/** Image attached to a user turn (session upload). */
export interface UserMessageAttachment {
  id: string;
  name?: string;
  /** Ephemeral object URL for live sends; omitted when replaying a stored session. */
  previewUrl?: string;
}

/**
 * A chat message rendered in the panel. User messages carry only `content`;
 * assistant messages also carry the retrieval `sources`, `steps` and `route`
 * returned by the backend so they can be re-rendered when a session is replayed.
 */
export interface ChatMessage {
  /** Stable client-side id (message_id once known). */
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Session image uploads shown in the user bubble. */
  attachments?: UserMessageAttachment[];
  sources?: QuerySources | null;
  steps?: Step[] | null;
  route?: RouteInfo | null;
  createdAt: string;
  /** True while waiting for the backend answer. */
  pending?: boolean;
  /** True while token stream is in progress. */
  streaming?: boolean;
  /** True for `/search` (retrieval-only) turns: sources render without an answer. */
  retrievalOnly?: boolean;
  /** Set when a turn fails, so the bubble can show an inline error affordance. */
  error?: boolean;
}

/**
 * Flattened, indexed view of a message's sources used to map answer citations
 * like `[1]`/`[2]` to a specific source card. Text sources are listed first,
 * then image sources — matching the backend's `{"text": [...], "image": [...]}`
 * ordering. The 1-based `index` is what `[n]` refers to.
 */
export interface FlatSource {
  index: number;
  type: "text" | "image";
  source: Record<string, unknown>;
}

export type { PreviewTarget } from "@/components/document-preview/types";

/** Layout density for the evidence rail and its expanded modal. */
export type PanelLayout = "rail" | "expanded";
