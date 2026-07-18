/**
 * Client-side ingest limits mirroring backend `ingest.limits` defaults.
 *
 * Keep in sync with `eagle_rag/settings.yaml` → `ingest.limits`
 * (MinerU Precision Extract API: 200 MiB / 200 pages).
 */

export const INGEST_MAX_FILE_BYTES = 209_715_200; // 200 MiB
export const INGEST_MAX_PDF_PAGES = 200;

export type IngestLimitCode = "file_too_large" | "pdf_too_many_pages" | "pdf_unreadable";

export interface IngestLimitViolation {
  code: IngestLimitCode;
  pages?: number;
  size?: number;
}

function stripRoutingPrefix(name: string): string {
  const lower = name.toLowerCase();
  if (lower.startsWith("knowhere:") || lower.startsWith("pixelrag:")) {
    return name.slice(name.indexOf(":") + 1);
  }
  return name;
}

function isPdfFilename(name: string): boolean {
  return stripRoutingPrefix(name).toLowerCase().endsWith(".pdf");
}

/**
 * Validate a staged file against size / PDF page limits before upload.
 * Returns a violation descriptor, or null when the file is within limits.
 */
export async function checkIngestFileLimits(file: File): Promise<IngestLimitViolation | null> {
  if (file.size > INGEST_MAX_FILE_BYTES) {
    return { code: "file_too_large", size: file.size };
  }
  if (!isPdfFilename(file.name)) {
    return null;
  }
  try {
    const { PDFDocument } = await import("pdf-lib");
    const bytes = await file.arrayBuffer();
    const pdf = await PDFDocument.load(bytes, { ignoreEncryption: true });
    const pages = pdf.getPageCount();
    if (pages > INGEST_MAX_PDF_PAGES) {
      return { code: "pdf_too_many_pages", pages };
    }
  } catch {
    return { code: "pdf_unreadable" };
  }
  return null;
}
