import { ApiError, apiErrorFromUnknown } from "./errors";
import { client } from "./generated/client.gen";
/**
 * Thin SSE subscription wrapper built on the hey-api generated `client.sse` and SDK functions.
 */
import type { StreamEvent } from "./generated/core/serverSentEvents.gen";
import { adminLogsAdminLogsGet, streamTaskTasksJobIdStreamGet } from "./generated/sdk.gen";
import type { QueryRequest, SearchRequest } from "./generated/types.gen";

export { ApiError };

/** Parsed SSE event (event name + raw data string). */
export interface SseEvent {
  event: string;
  data: string;
}

type SseHandler = (event: SseEvent) => void;
type SseErrorHandler = (err: Error) => void;
type SseCancel = () => void;

function toSseEvent(evt: StreamEvent<unknown>): SseEvent {
  return {
    event: evt.event ?? "message",
    data: typeof evt.data === "string" ? evt.data : JSON.stringify(evt.data),
  };
}

function subscribeSse(
  open: (handlers: {
    onSseEvent: (event: StreamEvent<unknown>) => void;
    onSseError: (error: unknown) => void;
    signal: AbortSignal;
  }) => Promise<{ stream: AsyncIterable<unknown> }>,
  onEvent: SseHandler,
  onError?: SseErrorHandler,
): SseCancel {
  const controller = new AbortController();
  void (async () => {
    try {
      const { stream } = await open({
        signal: controller.signal,
        onSseEvent: (evt) => onEvent(toSseEvent(evt)),
        onSseError: (error) => {
          if (!controller.signal.aborted) {
            onError?.(apiErrorFromUnknown(error));
          }
        },
      });
      for await (const _ of stream) {
        if (controller.signal.aborted) break;
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        onError?.(apiErrorFromUnknown(err));
      }
    }
  })();
  return () => controller.abort();
}

/** Subscribe to task progress SSE (`/tasks/{id}/stream`). */
export function streamTaskProgress(
  taskId: string,
  onEvent: SseHandler,
  onError?: SseErrorHandler,
): SseCancel {
  return subscribeSse(
    ({ onSseEvent, onSseError, signal }) =>
      streamTaskTasksJobIdStreamGet({
        path: { job_id: taskId },
        signal,
        onSseEvent,
        onSseError,
      }),
    onEvent,
    onError,
  );
}

/** Subscribe to ops real-time log SSE (`/admin/logs`). */
export function streamAdminLogs(onEvent: SseHandler, onError?: SseErrorHandler): SseCancel {
  return subscribeSse(
    ({ onSseEvent, onSseError, signal }) =>
      adminLogsAdminLogsGet({
        signal,
        onSseEvent,
        onSseError,
      }),
    onEvent,
    onError,
  );
}

/** Streaming query SSE (`POST /query/stream`). */
export function streamQuery(
  body: QueryRequest,
  onEvent: SseHandler,
  onError?: SseErrorHandler,
): SseCancel {
  return subscribeSse(
    ({ onSseEvent, onSseError, signal }) =>
      client.sse.post({
        url: "/query/stream",
        body,
        signal,
        onSseEvent,
        onSseError,
        headers: { "Content-Type": "application/json" },
      }),
    onEvent,
    onError,
  );
}

/** Streaming pure retrieval SSE (`POST /search/stream`). */
export function streamSearch(
  body: SearchRequest,
  onEvent: SseHandler,
  onError?: SseErrorHandler,
): SseCancel {
  return subscribeSse(
    ({ onSseEvent, onSseError, signal }) =>
      client.sse.post({
        url: "/search/stream",
        body,
        signal,
        onSseEvent,
        onSseError,
        headers: { "Content-Type": "application/json" },
      }),
    onEvent,
    onError,
  );
}
