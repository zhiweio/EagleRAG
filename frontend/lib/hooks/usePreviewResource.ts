"use client";

import { previewContentUrl } from "@/components/document-preview/preview-urls";
import { isExternalFilePreview } from "@/components/document-preview/resolve-renderer";
import type { PreviewTarget } from "@/components/document-preview/types";
import { previewCacheKey } from "@/lib/preview/preview-cache-key";
import {
  acquirePreviewObjectUrl,
  releasePreviewObjectUrl,
  revokePreviewObjectUrl,
} from "@/lib/preview/preview-object-url";
import type { PreviewResourceBlob } from "@/lib/preview/types";
import type { QueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

const PREVIEW_QUERY_ROOT = ["preview-resource"] as const;

/** Session cache: reopening a preview reuses bytes without another network fetch. */
const PREVIEW_STALE_MS = 30 * 60 * 1000;
const PREVIEW_GC_MS = 60 * 60 * 1000;

async function fetchPreviewBlob(url: string): Promise<PreviewResourceBlob> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Preview fetch failed (${response.status})`);
  }

  const blob = await response.blob();
  const headerType = response.headers.get("content-type")?.split(";")[0]?.trim();
  const mimeType = blob.type || headerType || "application/octet-stream";
  const typedBlob = !blob.type && headerType ? new Blob([blob], { type: headerType }) : blob;

  return { blob: typedBlob, mimeType };
}

function shouldSkipPreviewFetch(target: PreviewTarget | null): boolean {
  if (!target) return true;
  if (target.kind === "table" && Boolean(target.html)) return true;
  // Live URL corpus: /file 307s to an external origin; fetch body hits CORS.
  if (isExternalFilePreview(target)) return true;
  return false;
}

/**
 * Load preview bytes through TanStack Query (deduped fetch + in-memory cache).
 * Consumers receive a blob: URL; revoke happens on unmount while query data persists.
 */
export function usePreviewResource(target: PreviewTarget | null) {
  const cacheKey = target ? previewCacheKey(target) : null;
  const remoteUrl = target ? previewContentUrl(target) : undefined;
  const skipFetch = shouldSkipPreviewFetch(target);

  const query = useQuery({
    queryKey: [...PREVIEW_QUERY_ROOT, cacheKey],
    queryFn: () => {
      if (!remoteUrl) {
        throw new Error("Preview URL missing");
      }
      return fetchPreviewBlob(remoteUrl);
    },
    enabled: Boolean(cacheKey && remoteUrl && !skipFetch),
    staleTime: PREVIEW_STALE_MS,
    gcTime: PREVIEW_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const objectUrl = useMemo(() => {
    if (!cacheKey || !query.data) return undefined;
    return acquirePreviewObjectUrl(cacheKey, query.data.blob);
  }, [cacheKey, query.data]);

  useEffect(() => {
    if (!cacheKey) return;
    return () => releasePreviewObjectUrl(cacheKey);
  }, [cacheKey]);

  const needsNetwork = Boolean(cacheKey && remoteUrl && !skipFetch);

  return {
    src: skipFetch ? undefined : objectUrl,
    blob: skipFetch ? undefined : query.data?.blob,
    mimeType: skipFetch ? undefined : query.data?.mimeType,
    resourceKey: cacheKey,
    isLoading: needsNetwork && query.isPending && !query.data,
    isFetching: needsNetwork && query.isFetching,
    error: query.error,
  };
}

/** Drop cached preview bytes after ingest/delete so the next open refetches. */
export function invalidatePreviewResource(queryClient: QueryClient, documentId: string) {
  const cacheKey = `file:${documentId}`;
  revokePreviewObjectUrl(cacheKey);
  void queryClient.invalidateQueries({
    queryKey: [...PREVIEW_QUERY_ROOT, cacheKey],
  });
}

/** Warm the cache before opening the modal (optional). */
export function prefetchPreviewResource(queryClient: QueryClient, target: PreviewTarget) {
  if (shouldSkipPreviewFetch(target)) return;

  const cacheKey = previewCacheKey(target);
  const remoteUrl = previewContentUrl(target);
  if (!cacheKey || !remoteUrl) return;

  void queryClient.prefetchQuery({
    queryKey: [...PREVIEW_QUERY_ROOT, cacheKey],
    queryFn: () => fetchPreviewBlob(remoteUrl),
    staleTime: PREVIEW_STALE_MS,
  });
}
