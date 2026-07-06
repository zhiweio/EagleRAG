/** Cached document bytes served to viewers via short-lived blob: object URLs. */
export type PreviewResourceBlob = {
  blob: Blob;
  mimeType: string;
};
