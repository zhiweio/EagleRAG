/** Layout density for inline, rail, expanded panel, or fullscreen modal preview. */
export type PreviewLayout = "inline" | "rail" | "panel" | "modal";

/** Discriminated preview target consumed by DocumentPreview and the global modal. */
export type PreviewTarget =
  | { kind: "image"; imageId: string; title?: string }
  | {
      kind: "table";
      documentId: string;
      chunkId?: string;
      html?: string;
      title?: string;
    }
  | {
      kind: "file";
      documentId: string;
      title?: string;
      mimeType?: string | null;
      sourceType?: string | null;
      /** Original ingest URI (MinIO key or http(s) URL). Used to route web/URL previews. */
      sourceUri?: string | null;
    }
  | {
      kind: "attachment";
      attachmentId: string;
      title?: string;
      previewUrl?: string;
      mimeType?: string;
    };

export type RendererKind =
  | "image"
  | "table"
  | "pdf"
  | "docx"
  | "xlsx"
  | "csv"
  | "markdown"
  | "html"
  | "iframe";
