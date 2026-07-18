import type { Task } from "@/lib/types";

/** Four-state task phase: queued / processing / success / failed. */
export type TaskPhase = "pending" | "running" | "success" | "failed";

/** Processing pipeline kind. */
export type PipelineKindOrNull = "knowhere" | "pixelrag" | null;

/** Determine the pipeline kind from a task's pipeline field. */
export function pipelineKind(task: Task): PipelineKindOrNull {
  const p = (task.pipeline ?? "").toLowerCase();
  if (p.includes("pixel") || p.includes("visual")) return "pixelrag";
  if (p.includes("know") || p.includes("text")) return "knowhere";
  return null;
}

/** Normalize the backend's dynamic status string into one of the four phases. */
export function normalizeStatus(status: string | null | undefined): TaskPhase {
  const s = (status ?? "").toLowerCase();
  if (s === "success" || s === "done" || s === "ready") return "success";
  if (s === "failed" || s === "error") return "failed";
  if (s === "pending" || s === "queued") return "pending";
  return "running";
}

/** Prefer API ``status_phase`` when present; otherwise derive from raw ``status``. */
export function taskPhase(task: Pick<Task, "status" | "status_phase">): TaskPhase {
  const phase = (task.status_phase ?? "").toLowerCase();
  if (phase === "pending" || phase === "running" || phase === "success" || phase === "failed") {
    return phase;
  }
  return normalizeStatus(task.status);
}

/** Which primary action the Actions column should expose for a task row. */
export type TaskRowAction = "cancel" | "retry" | "none";

/**
 * Actions column policy:
 * - pending/queued → Cancel (delete audit)
 * - failed/error → Retry
 * - retrying → Retry (manual re-dispatch while Celery auto-retry waits)
 * - running / success → none ("—")
 */
export function taskRowAction(task: Pick<Task, "status" | "status_phase">): TaskRowAction {
  const raw = (task.status ?? "").toLowerCase();
  const phase = taskPhase(task);
  if (phase === "pending") return "cancel";
  if (phase === "failed" || raw === "retrying") return "retry";
  return "none";
}

/** Phase → semantic tone (used for status dots, progress bars, row tints). */
export const PHASE_TONE: Record<TaskPhase, "warning" | "accent" | "success" | "danger"> = {
  pending: "warning",
  running: "accent",
  success: "success",
  failed: "danger",
};

/**
 * Uppercased display label for the State column. Prefers the raw backend status
 * (e.g. RENDERING / EMBEDDING) and falls back to the normalized phase when unknown.
 * The design uses the uppercased raw status directly.
 */
export function stateLabel(task: Task): string {
  const raw = (task.status ?? "").trim();
  if (raw) return raw.toUpperCase();
  return normalizeStatus(task.status).toUpperCase();
}

/** Progress percentage: prefers current/total, falls back to the progress field. */
export function progressPercent(task: Task): number {
  if (task.total && task.current != null && task.total > 0) {
    return Math.min(100, Math.round((task.current / task.total) * 100));
  }
  const p = typeof task.progress === "number" ? task.progress : 0;
  return Math.max(0, Math.min(100, p));
}

/** Derive a display document name from a task. */
export function documentName(task: Task): string {
  const name = task.name;
  if (typeof name === "string" && name.trim()) return name;
  const uri = task.source_uri;
  if (typeof uri === "string" && uri.trim()) {
    const base = uri.split(/[\\/]/).pop() ?? uri;
    try {
      return decodeURIComponent(base) || uri;
    } catch {
      return uri;
    }
  }
  return task.document_id ?? task.job_id;
}

/** SSE payload → Task (defensive parsing). */
export function parseTask(data: string): Task | null {
  try {
    const parsed = JSON.parse(data) as Task;
    return typeof parsed?.job_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}
