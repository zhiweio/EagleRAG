import { client } from "@/lib/api/generated/client.gen";
import {
  adminCeleryAdminCeleryGet,
  adminConfigAdminConfigGet,
  adminKnowhereAdminKnowhereGet,
  adminMcpAdminMcpGet,
  adminMilvusAdminMilvusGet,
  adminMinioAdminMinioGet,
  adminPixelragAdminPixelragGet,
  adminProbesAdminProbesGet,
  adminRedisAdminRedisGet,
  adminUpdateModelRouterAdminModelRouterPatch,
  adminVlmAdminVlmGet,
  healthHealthGet,
  mcpToolsMcpToolsGet,
} from "@/lib/api/generated/sdk.gen";
import { streamAdminLogs } from "@/lib/api/sse";
import type { SseEvent } from "@/lib/api/sse";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

/** 30s polling interval (matches the existing useNotifications interval). */
const HEALTH_POLL_MS = 30_000;

/** SSE log buffer cap (older entries are truncated). */
const ADMIN_LOG_MAX_LINES = 500;

/** GET /health — dependency service health probe. */
export function useHealth(enabled = true) {
  return useQuery({
    queryKey: ["health"],
    enabled,
    queryFn: async () => {
      const r = await healthHealthGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /mcp/tools — MCP tool list. */
export function useMcpTools(enabled = true) {
  return useQuery({
    queryKey: ["mcp-tools"],
    enabled,
    queryFn: async () => {
      const r = await mcpToolsMcpToolsGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/celery */
export function useAdminCelery(enabled = true) {
  return useQuery({
    queryKey: ["admin", "celery"],
    enabled,
    queryFn: async () => {
      const r = await adminCeleryAdminCeleryGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/milvus */
export function useAdminMilvus(enabled = true) {
  return useQuery({
    queryKey: ["admin", "milvus"],
    enabled,
    queryFn: async () => {
      const r = await adminMilvusAdminMilvusGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/minio */
export function useAdminMinio(enabled = true) {
  return useQuery({
    queryKey: ["admin", "minio"],
    enabled,
    queryFn: async () => {
      const r = await adminMinioAdminMinioGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/redis */
export function useAdminRedis(enabled = true) {
  return useQuery({
    queryKey: ["admin", "redis"],
    enabled,
    queryFn: async () => {
      const r = await adminRedisAdminRedisGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/knowhere */
export function useAdminKnowhere(enabled = true) {
  return useQuery({
    queryKey: ["admin", "knowhere"],
    enabled,
    queryFn: async () => {
      const r = await adminKnowhereAdminKnowhereGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/vlm */
export function useAdminVlm(enabled = true) {
  return useQuery({
    queryKey: ["admin", "vlm"],
    enabled,
    queryFn: async () => {
      const r = await adminVlmAdminVlmGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/pixelrag */
export function useAdminPixelrag(enabled = true) {
  return useQuery({
    queryKey: ["admin", "pixelrag"],
    enabled,
    queryFn: async () => {
      const r = await adminPixelragAdminPixelragGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/mcp */
export function useAdminMcp(enabled = true) {
  return useQuery({
    queryKey: ["admin", "mcp"],
    enabled,
    queryFn: async () => {
      const r = await adminMcpAdminMcpGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/config */
export function useAdminConfig(enabled = true) {
  return useQuery({
    queryKey: ["admin", "config"],
    enabled,
    queryFn: async () => {
      const r = await adminConfigAdminConfigGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** GET /admin/probes */
export function useAdminProbes(enabled = true) {
  return useQuery({
    queryKey: ["admin", "probes"],
    enabled,
    queryFn: async () => {
      const r = await adminProbesAdminProbesGet();
      if (r.error) throw r.error;
      return r.data;
    },
    refetchInterval: HEALTH_POLL_MS,
  });
}

/** PATCH /admin/model-router — update model-router toggles. */
export function useUpdateModelRouter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      vlm?: boolean;
      text_llm?: boolean;
      embedding?: boolean;
    }) => {
      const r = await adminUpdateModelRouterAdminModelRouterPatch({ body });
      if (r.error) throw r.error;
      return r.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "vlm"] });
    },
  });
}

/** Maintenance action result (flush / compact). */
export interface AdminActionResult {
  success: boolean;
  message: string;
  details?: { collection: string; action: string; success: boolean; detail?: string }[];
}

async function postAdminAction(url: string): Promise<AdminActionResult> {
  const r = await client.post<AdminActionResult>({ url });
  if (r.error) throw r.error;
  return r.data as AdminActionResult;
}

/** POST /admin/milvus/flush — force-flush all Milvus collections. */
export function useMilvusFlush() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => postAdminAction("/admin/milvus/flush"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "milvus"] }),
  });
}

/** POST /admin/milvus/clean — compact all Milvus collections. */
export function useMilvusClean() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => postAdminAction("/admin/milvus/clean"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "milvus"] }),
  });
}

/** POST /admin/knowhere/flush — force-flush the eagle_text collection. */
export function useKnowhereFlush() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => postAdminAction("/admin/knowhere/flush"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "knowhere"] }),
  });
}

/** POST /admin/knowhere/clean — compact eagle_text collection */
export function useKnowhereClean() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => postAdminAction("/admin/knowhere/clean"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "knowhere"] }),
  });
}

/* ------------------------------------------------------------------ *
 * SSE log subscription
 * ------------------------------------------------------------------ */

export interface AdminLogLine {
  time: string;
  /** "INFO" | "WARN" | "ERROR" | "DEBUG" | etc. (uppercased). */
  level: string;
  source: string;
  message: string;
}

/**
 * Subscribe to the /admin/logs SSE stream and accumulate log lines.
 *
 * Backend event format:
 *   - `heartbeat` events: ignored
 *   - other events' `data` is JSON: `{ level, message, timestamp, source? }`
 *   - non-JSON `data`: treated as a plain-text message
 *
 * @returns
 *   - `lines`: accumulated log lines (capped at 500; older entries truncated)
 *   - `clear`: clears the accumulated log lines
 *   - `connected`: whether the SSE connection is currently open
 */
export function useAdminLogs(enabled = true) {
  const [lines, setLines] = useState<AdminLogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const cancel = streamAdminLogs(
      (event: SseEvent) => {
        if (event.event === "heartbeat") return;
        try {
          const payload = JSON.parse(event.data) as {
            level?: string;
            message?: string;
            timestamp?: string;
            source?: string;
          };
          setLines((prev) => {
            const line: AdminLogLine = {
              time: payload.timestamp || new Date().toISOString(),
              level: (payload.level || "info").toUpperCase(),
              source: payload.source || "",
              message: payload.message || "",
            };
            const next = [...prev, line];
            return next.length > ADMIN_LOG_MAX_LINES ? next.slice(-ADMIN_LOG_MAX_LINES) : next;
          });
        } catch {
          // Non-JSON data: treat as a plain-text message.
          setLines((prev) => {
            const line: AdminLogLine = {
              time: new Date().toISOString(),
              level: "INFO",
              source: "",
              message: event.data,
            };
            const next = [...prev, line];
            return next.length > ADMIN_LOG_MAX_LINES ? next.slice(-ADMIN_LOG_MAX_LINES) : next;
          });
        }
      },
      () => setConnected(false),
    );
    cancelRef.current = cancel;
    setConnected(true);

    return () => {
      cancel();
      setConnected(false);
    };
  }, [enabled]);

  const clear = useCallback(() => setLines([]), []);

  return { lines, clear, connected };
}
