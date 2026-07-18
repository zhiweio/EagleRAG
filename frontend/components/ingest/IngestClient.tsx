"use client";

import { IngestToast, type IngestToastItem } from "@/components/ingest/IngestToast";
import { QueueMetrics } from "@/components/ingest/QueueMetrics";
import { type RoutingMode, RoutingModeCards } from "@/components/ingest/RoutingModeCards";
import { TargetKBSelector } from "@/components/ingest/TargetKBSelector";
import { TaskLogsModal } from "@/components/ingest/TaskLogsModal";
import { TaskTable } from "@/components/ingest/TaskTable";
import { TaskToolbar } from "@/components/ingest/TaskToolbar";
import { UploadZone } from "@/components/ingest/UploadZone";
import { UrlInputZone } from "@/components/ingest/UrlInputZone";
import { normalizeStatus, pipelineKind } from "@/components/ingest/status";
import { Card, Chip, PageHeader } from "@/components/ui";
import { errorMessage, useDeleteTask, useRetryTask, useTasks } from "@/lib/hooks/useIngest";
import { useKnowledgeBases } from "@/lib/hooks/useKB";
import { useUserPreferences } from "@/lib/hooks/useUser";
import { useFilterStore } from "@/lib/stores/filterStore";
import { useKBStore } from "@/lib/stores/kbStore";
import { useUIStore } from "@/lib/stores/uiStore";
import type { IngestResponse, Task } from "@/lib/types";
import { Globe, LibraryBig, UploadCloud } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";

const DEFAULT_POLL_INTERVAL = 5000;

/** Ingest page orchestrator: wires upload, queue metrics, toolbar, task table, log modal, and toasts.
 * Data fetching is handled by useTasks (react-query); filter / kbName state lives in the zustand store.
 * Task progress on the list uses polling; SSE is only opened from TaskLogsModal. */
export function IngestClient() {
  const t = useTranslations("ingest");

  const { kbName, setKbName } = useKBStore();
  const { taskFilter } = useFilterStore();
  const { query, pipelines, statuses, autoPoll } = taskFilter;
  const { ingestLogsJobId, setIngestLogsJobId } = useUIStore();

  const [submitMode, setSubmitMode] = useState<"file" | "url">("file");
  const [mode, setMode] = useState<RoutingMode>("auto");

  const { data: kbList } = useKnowledgeBases({ limit: 200, sort: "name" });
  const kbOptions = kbList?.items ?? [];
  const { data: userPrefs } = useUserPreferences();
  const pollInterval = userPrefs?.ingest_poll_interval_ms ?? DEFAULT_POLL_INTERVAL;

  // useTasks params: server-side filters kb_name / q; pipeline/status use normalized
  // semantic labels (knowhere/pixelrag, pending/running, …) that differ from the raw
  // backend values, so they are always re-filtered on the client.
  const tasksParams = useMemo(
    () => ({
      limit: 500,
      kb_name: kbName || undefined,
      q: query.trim() || undefined,
    }),
    [kbName, query],
  );
  const tasksQuery = useTasks(tasksParams, {
    refetchInterval: autoPoll ? pollInterval : false,
  });
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const loading = tasksQuery.isLoading;
  const refreshing = tasksQuery.isFetching && !tasksQuery.isLoading;
  const error = tasksQuery.error ? errorMessage(tasksQuery.error) : null;

  const [toasts, setToasts] = useState<IngestToastItem[]>([]);

  const filteredTasks = useMemo(() => {
    if (pipelines.length === 0 && statuses.length === 0) return tasks;
    return tasks.filter((task) => {
      if (pipelines.length > 0) {
        const kind = pipelineKind(task);
        if (!kind || !pipelines.includes(kind)) return false;
      }
      if (statuses.length > 0 && !statuses.includes(normalizeStatus(task.status))) return false;
      return true;
    });
  }, [tasks, pipelines, statuses]);

  // Per-dimension counts: drive the toolbar filter badges (kb / pipeline / status).
  const counts = useMemo(() => {
    const kb: Record<string, number> = {};
    const pipeline: Record<string, number> = {};
    const status: Record<string, number> = {};
    for (const task of tasks) {
      if (task.kb_name) kb[task.kb_name] = (kb[task.kb_name] ?? 0) + 1;
      const kind = pipelineKind(task);
      if (kind) pipeline[kind] = (pipeline[kind] ?? 0) + 1;
      const phase = normalizeStatus(task.status);
      status[phase] = (status[phase] ?? 0) + 1;
    }
    return { kb, pipeline, status };
  }, [tasks]);

  const pushToast = useCallback((item: Omit<IngestToastItem, "id">) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev, { ...item, id }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  // File ingest: dedup hit / immediate success uses success toast; pending is covered by onBatch.
  const handleIngested = useCallback(
    (resp: IngestResponse, name: string) => {
      if (resp.status === "pending") {
        return;
      }
      pushToast({
        variant: "success",
        title: t("toast.success"),
        description: name,
        documentId: resp.document_id ?? undefined,
      });
    },
    [pushToast, t],
  );

  const handleIngestError = useCallback(
    (name: string, message: string) => {
      pushToast({ variant: "error", title: t("toast.failed"), description: `${name}: ${message}` });
    },
    [pushToast, t],
  );

  // Queue count: number of non-terminal (queued / running) tasks; drives the header queue chip and the created-toast position estimate.
  const queueCount = useMemo(
    () =>
      tasks.filter((task) => {
        const s = normalizeStatus(task.status);
        return s === "running" || s === "pending";
      }).length,
    [tasks],
  );

  // Batch submit callback: shows the "created N ingest tasks" toast and estimates the queue position.
  const handleBatch = useCallback(
    (count: number) => {
      if (count <= 0) return;
      const start = queueCount + 1;
      const end = queueCount + count;
      const range = count > 1 ? `#${start}-${end}` : `#${start}`;
      pushToast({
        variant: "created",
        title: t("toast.created", { count }),
        hint: t("toast.createdHint", { range }),
      });
    },
    [pushToast, t, queueCount],
  );

  const handleUrlQueued = useCallback(() => {
    const start = queueCount + 1;
    pushToast({
      variant: "created",
      title: t("toast.queued"),
      hint: t("toast.createdHint", { range: `#${start}` }),
    });
  }, [pushToast, t, queueCount]);

  const retryTask = useRetryTask();
  const handleRetry = useCallback(
    async (task: Task) => {
      try {
        await retryTask.mutateAsync(task.job_id);
      } catch (err) {
        pushToast({
          variant: "error",
          title: t("toast.failed"),
          description: errorMessage(err),
        });
      }
    },
    [retryTask, pushToast, t],
  );

  const deleteTask = useDeleteTask();
  const handleDelete = useCallback(
    async (task: Task) => {
      try {
        await deleteTask.mutateAsync(task.job_id);
      } catch (err) {
        pushToast({
          variant: "error",
          title: t("toast.failed"),
          description: errorMessage(err),
        });
      }
    },
    [deleteTask, pushToast, t],
  );

  // Current task for the log modal: open/close is driven by uiStore.ingestLogsJobId;
  // the task object is looked up from the useTasks cache.
  const logsTask = useMemo(
    () =>
      ingestLogsJobId ? (tasks.find((task) => task.job_id === ingestLogsJobId) ?? null) : null,
    [tasks, ingestLogsJobId],
  );

  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <PageHeader
          title={t("title")}
          subtitle={t("subtitle")}
          actions={
            <Chip tone="accent" dot>
              {t("header.inQueue", { count: queueCount })}
            </Chip>
          }
        />

        <Card flush>
          <div className="p-5">
            {/* Target KB selector (shared) */}
            <div className="flex flex-col gap-2">
              <span className="flex items-center gap-2 text-xs font-semibold text-foreground-secondary">
                <LibraryBig className="h-3.5 w-3.5" aria-hidden />
                {t("upload.targetKB")}
                <Chip tone="danger" size="sm">
                  {t("upload.required")}
                </Chip>
              </span>
              <TargetKBSelector items={kbOptions} value={kbName} onChange={setKbName} />
            </div>

            {/* Routing mode cards (shared) */}
            <div className="mt-4">
              <RoutingModeCards value={mode} onChange={setMode} />
            </div>

            {/* Tab switcher */}
            <div className="mt-4 flex justify-center">
              <div className="inline-flex h-9 items-stretch gap-0.5 rounded-lg bg-(--surface-muted) p-0.5">
                <button
                  type="button"
                  onClick={() => setSubmitMode("file")}
                  aria-pressed={submitMode === "file"}
                  className={`flex items-center gap-1.5 rounded-md px-3 text-[12px] font-medium transition-colors ${
                    submitMode === "file"
                      ? "bg-surface font-semibold text-foreground shadow-sm"
                      : "text-foreground-secondary hover:text-foreground"
                  }`}
                >
                  <UploadCloud className="h-4 w-4" aria-hidden />
                  {t("url.tab.file")}
                </button>
                <button
                  type="button"
                  onClick={() => setSubmitMode("url")}
                  aria-pressed={submitMode === "url"}
                  className={`flex items-center gap-1.5 rounded-md px-3 text-[12px] font-medium transition-colors ${
                    submitMode === "url"
                      ? "bg-surface font-semibold text-foreground shadow-sm"
                      : "text-foreground-secondary hover:text-foreground"
                  }`}
                >
                  <Globe className="h-4 w-4" aria-hidden />
                  {t("url.tab.url")}
                </button>
              </div>
            </div>

            {/* Submission area */}
            <div className="mt-4">
              {submitMode === "file" ? (
                <UploadZone
                  onIngested={handleIngested}
                  onError={handleIngestError}
                  onBatch={handleBatch}
                  kbName={kbName}
                  mode={mode}
                />
              ) : (
                <UrlInputZone
                  onIngested={handleIngested}
                  onError={handleIngestError}
                  onQueued={handleUrlQueued}
                  kbName={kbName}
                  mode={mode}
                />
              )}
            </div>
          </div>
        </Card>

        <QueueMetrics tasks={tasks} />

        <Card flush>
          <div className="border-b border-border p-4">
            <TaskToolbar
              onRefresh={() => void tasksQuery.refetch()}
              refreshing={refreshing}
              kbItems={kbOptions}
              counts={counts}
            />
          </div>
          <TaskTable
            tasks={filteredTasks}
            loading={loading}
            error={error}
            onRetry={(task) => void handleRetry(task)}
            onDelete={(task) => void handleDelete(task)}
            onViewLogs={(task) => setIngestLogsJobId(task.job_id)}
            onRetryLoad={() => void tasksQuery.refetch()}
          />
        </Card>
      </main>

      {logsTask && (
        <TaskLogsModal
          task={logsTask}
          onClose={() => setIngestLogsJobId(null)}
          onRetry={(task) => void handleRetry(task)}
        />
      )}
      <IngestToast toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
