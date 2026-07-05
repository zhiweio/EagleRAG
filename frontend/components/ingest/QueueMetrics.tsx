"use client";

import { QUEUE_GREEN, QUEUE_PURPLE, QueueCard } from "@/components/ingest/QueueCard";
import { normalizeStatus } from "@/components/ingest/status";
import { useIngestQueueMetrics } from "@/lib/hooks/useIngest";
import type { Task } from "@/lib/types";
import { FileText, Image } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

function isKnowhere(task: Task): boolean {
  const p = (task.pipeline ?? "").toLowerCase();
  return p.includes("know") || p.includes("text");
}
function isPixelrag(task: Task): boolean {
  const p = (task.pipeline ?? "").toLowerCase();
  return p.includes("pixel") || p.includes("visual");
}

interface QueueMetricsProps {
  tasks: Task[];
}

/**
 * QueueMetrics — ingest queue area: title "Ingestion Queue · Live" + two queue cards
 * (green text parsing / purple visual rendering). Concurrency dots change with the
 * live running/queued task counts.
 */
export function QueueMetrics({ tasks }: QueueMetricsProps) {
  const t = useTranslations("ingest.queue");

  const queueMetrics = useIngestQueueMetrics();
  const knowhereConcurrency = queueMetrics.data?.knowhereConcurrency ?? 8;
  const pixelragConcurrency = queueMetrics.data?.pixelragConcurrency ?? 1;

  const stats = useMemo(() => {
    let textRunning = 0;
    let visualRunning = 0;
    let visualQueued = 0;
    for (const task of tasks) {
      const phase = normalizeStatus(task.status);
      if (isKnowhere(task) && phase === "running") textRunning += 1;
      if (isPixelrag(task)) {
        if (phase === "running") visualRunning += 1;
        else if (phase === "pending") visualQueued += 1;
      }
    }
    return { textRunning, visualRunning, visualQueued };
  }, [tasks]);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold text-foreground">{t("title")}</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-1 text-[11px] font-semibold text-success">
          <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
          {t("live")}
        </span>
      </div>

      <div className="flex flex-col gap-4 md:flex-row">
        <QueueCard
          icon={FileText}
          palette={QUEUE_GREEN}
          title={t("text.title")}
          worker={t("text.worker")}
          pillLabel={stats.textRunning > 0 ? t("text.busy") : t("text.idle")}
          footer={t("text.concurrency", { count: knowhereConcurrency })}
          dots={{
            total: knowhereConcurrency,
            filled: Math.max(stats.textRunning, knowhereConcurrency),
          }}
        />
        <QueueCard
          icon={Image}
          palette={QUEUE_PURPLE}
          title={t("visual.title")}
          worker={t("visual.worker")}
          pillLabel={stats.visualQueued > 0 ? t("visual.queued") : t("visual.idle")}
          footer={t("visual.concurrency", {
            queued: stats.visualQueued,
            count: pixelragConcurrency,
          })}
          dots={{
            total: pixelragConcurrency,
            filled: Math.min(stats.visualRunning, pixelragConcurrency),
          }}
        />
      </div>
    </section>
  );
}
