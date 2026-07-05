import {
  deleteTaskTasksJobIdDelete,
  getTaskLogsTasksJobIdLogsGet,
  getTaskTasksJobIdGet,
  ingestQueueMetricsIngestQueueMetricsGet,
  listTasksTasksGet,
  postIngestIngestPost,
  retryTaskTasksJobIdRetryPost,
} from "@/lib/api/generated/sdk.gen";
import type {
  AckResponse,
  IngestResponse,
  Task,
  TaskListParams,
  TaskListResponse,
  TaskLogsResponse,
  TaskRetryResponse,
} from "@/lib/types";
/**
 * ingest domain hooks: task audit and document ingestion.
 *
 * Queries: useTasks / useTask / useTaskLogs
 * Mutations: useIngestFile / useIngestUrl / useRetryTask / useDeleteTask
 *
 * queryKey is organised by domain + params to ensure cache is correctly isolated
 * when filters such as kb_name change; mutations invalidate the corresponding
 * query keys on success to refresh the list.
 * Since the backend returns untyped dict, values are asserted via unknown to the
 * target type.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryOptions } from "@tanstack/react-query";

/**
 * Extract a readable message from the error object thrown by the hey-api client.
 *
 * The generated client throws `JSON.parse(response.text())` on non-2xx (often
 * `{detail: "..."}`) or a plain string, and may also be an empty object. This
 * helper normalises everything to a string for UI display.
 */
export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  if (err && typeof err === "object") {
    const obj = err as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    if (typeof obj.message === "string") return obj.message;
  }
  return String(err);
}

/**
 * Structured error codes returned by the backend URL prefetch layer.
 * See `eagle_rag/ingest/url_validator.py` for the source of these codes.
 */
export type UrlErrorCode =
  | "invalid_url_format"
  | "url_target_forbidden"
  | "url_unreachable"
  | "url_timeout"
  | "url_bad_status";

/**
 * Structured URL ingest error parsed from a 422 response body.
 * Mirrors `UrlValidationErrorDetail` on the backend.
 */
export interface UrlIngestError {
  code: UrlErrorCode | string;
  reason: string;
  suggestion?: string;
}

/**
 * Parse a structured URL ingest error from the value thrown by the hey-api client.
 *
 * The backend returns `HTTPException(status_code=422, detail=exc.to_detail())`
 * where `to_detail()` is `{"code": "...", "reason": "...", "suggestion": "..."}`.
 * The hey-api client throws the parsed JSON body, so the caught error has the
 * shape `{detail: {code, reason, suggestion}}`. When `detail` is a plain string
 * (other validation errors) this returns null so callers fall back to
 * `errorMessage`.
 */
export function parseUrlIngestError(err: unknown): UrlIngestError | null {
  if (!err || typeof err !== "object") return null;
  const obj = err as Record<string, unknown>;
  const detail = obj.detail;
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== "string" || typeof d.reason !== "string") return null;
  return {
    code: d.code,
    reason: d.reason,
    suggestion: typeof d.suggestion === "string" ? d.suggestion : undefined,
  };
}

export function useTasks(
  params?: TaskListParams,
  options?: Omit<
    UseQueryOptions<TaskListResponse, Error, TaskListResponse>,
    "queryKey" | "queryFn"
  >,
) {
  return useQuery({
    queryKey: ["tasks", params],
    queryFn: async () => {
      const result = await listTasksTasksGet({ query: params });
      if (result.error) throw result.error;
      return result.data as unknown as TaskListResponse;
    },
    ...options,
  });
}

export function useTask(jobId: string) {
  return useQuery({
    queryKey: ["task", jobId],
    queryFn: async () => {
      const result = await getTaskTasksJobIdGet({ path: { job_id: jobId } });
      if (result.error) throw result.error;
      return result.data as unknown as Task;
    },
  });
}

export function useTaskLogs(jobId: string) {
  return useQuery({
    queryKey: ["task-logs", jobId],
    queryFn: async () => {
      const result = await getTaskLogsTasksJobIdLogsGet({ path: { job_id: jobId } });
      if (result.error) throw result.error;
      return result.data as unknown as TaskLogsResponse;
    },
  });
}

export function useIngestFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { file: File; source_type_hint?: string; kb_name?: string }) => {
      const result = await postIngestIngestPost({
        body: {
          file: vars.file,
          source_type_hint: vars.source_type_hint,
          kb_name: vars.kb_name,
        },
      });
      if (result.error) throw result.error;
      return result.data as unknown as IngestResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useIngestUrl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { url: string; source_type_hint?: string; kb_name?: string }) => {
      const result = await postIngestIngestPost({
        body: {
          url: vars.url,
          source_type_hint: vars.source_type_hint,
          kb_name: vars.kb_name,
        },
      });
      if (result.error) throw result.error;
      return result.data as unknown as IngestResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useRetryTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: string) => {
      const result = await retryTaskTasksJobIdRetryPost({ path: { job_id: jobId } });
      if (result.error) throw result.error;
      return result.data as unknown as TaskRetryResponse;
    },
    onSuccess: (_data, jobId) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["task", jobId] });
    },
  });
}

export function useDeleteTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: string) => {
      const result = await deleteTaskTasksJobIdDelete({ path: { job_id: jobId } });
      if (result.error) throw result.error;
      return result.data as unknown as AckResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

/** Ingest queue metrics: per-Celery-queue concurrency cap (from backend settings) + backlog length (Redis LLEN). */
export interface IngestQueueMetrics {
  knowhereConcurrency: number;
  pixelragConcurrency: number;
  knowhereSize: number | null;
  pixelragSize: number | null;
}

/**
 * useIngestQueueMetrics — fetch ingest queue concurrency config and backlog size.
 *
 * Concurrency limits come from the backend settings.yaml (static config, always
 * available); size comes from Redis LLEN (best-effort, null when backend is
 * unreachable). Auto-refreshes every 5s to reflect the live backlog. The endpoint
 * always returns 200; the query only errors on network-layer failure (consumers
 * fall back to defaults).
 */
export function useIngestQueueMetrics() {
  return useQuery({
    queryKey: ["ingest", "queue-metrics"],
    queryFn: async () => {
      const result = await ingestQueueMetricsIngestQueueMetricsGet();
      if (result.error) throw result.error;
      const data = result.data as {
        queues: Array<{ name: string; concurrency: number; size?: number | null }>;
      };
      const byName = new Map(data.queues.map((q) => [q.name, q]));
      return {
        knowhereConcurrency: byName.get("knowhere_queue")?.concurrency ?? 8,
        pixelragConcurrency: byName.get("pixelrag_queue")?.concurrency ?? 1,
        knowhereSize: byName.get("knowhere_queue")?.size ?? null,
        pixelragSize: byName.get("pixelrag_queue")?.size ?? null,
      } satisfies IngestQueueMetrics;
    },
    refetchInterval: 5000,
  });
}
