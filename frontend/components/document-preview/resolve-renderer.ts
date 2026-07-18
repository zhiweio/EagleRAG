import type { PreviewTarget, RendererKind } from "./types";

const IMAGE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "bmp",
  "tif",
  "tiff",
  "svg",
]);

function extensionOf(name: string | undefined | null): string {
  if (!name) return "";
  const base = name.split(/[?#]/)[0] ?? name;
  const idx = base.lastIndexOf(".");
  return idx >= 0 ? base.slice(idx + 1).toLowerCase() : "";
}

function isImageMime(mime: string | undefined | null): boolean {
  return Boolean(mime?.startsWith("image/"));
}

function isHttpUri(value: string | undefined | null): boolean {
  if (!value) return false;
  const lower = value.trim().toLowerCase();
  return lower.startsWith("http://") || lower.startsWith("https://");
}

function fileHints(target: Extract<PreviewTarget, { kind: "file" }>) {
  const ext = extensionOf(target.title);
  const mime = target.mimeType?.toLowerCase() ?? "";
  const source = target.sourceType?.toLowerCase() ?? "";

  const isPdf = ext === "pdf" || mime === "application/pdf" || source.includes("pdf");
  const isDocx =
    ext === "docx" ||
    mime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    source === "docx";
  const isXlsx =
    ext === "xlsx" ||
    ext === "xls" ||
    mime.includes("spreadsheet") ||
    mime.includes("excel") ||
    source === "xlsx" ||
    source === "xls";
  const isCsv =
    ext === "csv" ||
    ext === "tsv" ||
    mime === "text/csv" ||
    mime === "text/tab-separated-values" ||
    source === "csv";
  const isImage = IMAGE_EXTENSIONS.has(ext) || isImageMime(mime);
  const isMarkdown =
    ext === "md" || ext === "markdown" || mime === "text/markdown" || mime === "text/x-markdown";
  const isHtml =
    ext === "html" ||
    ext === "htm" ||
    mime === "text/html" ||
    isHttpUri(target.sourceUri) ||
    isHttpUri(target.title);

  return { ext, isPdf, isDocx, isXlsx, isCsv, isImage, isMarkdown, isHtml };
}

/** Pick the viewer implementation for a preview target. */
export function resolveRenderer(target: PreviewTarget): RendererKind {
  if (target.kind === "image") return "image";
  if (target.kind === "table") return "table";
  if (target.kind === "attachment") return "image";

  const hints = fileHints(target);
  if (hints.isPdf) return "pdf";
  if (hints.isDocx) return "docx";
  if (hints.isXlsx) return "xlsx";
  if (hints.isCsv) return "csv";
  if (hints.isImage) return "image";
  if (hints.isMarkdown) return "markdown";
  if (hints.isHtml) return "html";
  return "iframe";
}

/** True when the file preview should iframe a live http(s) URL (no blob cache). */
export function isExternalFilePreview(target: PreviewTarget | null | undefined): boolean {
  return target?.kind === "file" && isHttpUri(target.sourceUri);
}
