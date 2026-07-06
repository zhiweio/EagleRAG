type ObjectUrlEntry = {
  url: string;
  refs: number;
};

const registry = new Map<string, ObjectUrlEntry>();

/** Share one blob: URL per cache key; survives preview surface unmount/remount. */
export function acquirePreviewObjectUrl(cacheKey: string, blob: Blob): string {
  const existing = registry.get(cacheKey);
  if (existing) {
    existing.refs += 1;
    return existing.url;
  }

  const url = URL.createObjectURL(blob);
  registry.set(cacheKey, { url, refs: 1 });
  return url;
}

export function releasePreviewObjectUrl(cacheKey: string): void {
  const entry = registry.get(cacheKey);
  if (!entry) return;

  entry.refs = Math.max(0, entry.refs - 1);
  // Keep the object URL alive for the session; revokePreviewObjectUrl clears it on invalidation.
}

export function peekPreviewObjectUrl(cacheKey: string): string | undefined {
  return registry.get(cacheKey)?.url;
}

export function revokePreviewObjectUrl(cacheKey: string): void {
  const entry = registry.get(cacheKey);
  if (!entry) return;

  URL.revokeObjectURL(entry.url);
  registry.delete(cacheKey);
}
