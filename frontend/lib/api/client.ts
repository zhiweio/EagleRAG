/**
 * Runtime config for the hey-api generated client.
 *
 * - baseUrl reads NEXT_PUBLIC_API_BASE (default http://localhost:8000)
 * - request interceptor: extension point for auth headers
 * - response interceptor: unified success handling
 * - error interceptor: unified error handling
 */
import { client } from "./generated/client.gen";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** Image byte-stream URL (used as `<img src>`; no GET wrapper in the OpenAPI spec). */
export function imageUrl(imageId: string): string {
  return `${API_BASE}/images/${encodeURIComponent(imageId)}`;
}

/**
 * Original ingested file URL for inline preview (`<img>` / `<iframe src>`).
 *
 * Serves the raw bytes for MinIO-backed sources or 307-redirects to the
 * external URL for `http(s)` sources. Consumed by the evidence File Preview.
 */
export function fileUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`;
}

/**
 * Knowhere table/visual chunk HTML URL (`<iframe src>` for the table preview).
 *
 * Returns the chunk's rendered HTML from MinIO with a Milvus fallback.
 */
export function chunkHtmlUrl(documentId: string, chunkId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(
    chunkId,
  )}`;
}

// Configure the generated client's baseUrl.
client.setConfig({
  baseUrl: API_BASE,
});

// Request interceptor (extensible for auth).
client.interceptors.request.use((request, _options) => {
  // Add Authorization or other headers here.
  return request;
});

// Response interceptor (extensible for unified success handling).
client.interceptors.response.use((response, _request, _options) => {
  return response;
});

// Error interceptor: unified error handling.
client.interceptors.error.use((error, _response, _request, _options) => {
  // Error logging or unified reporting.
  console.error("[API Error]", error);
  return error;
});

export { client };
