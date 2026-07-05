"use client";

import { HealthQueueChart } from "@/components/charts/HealthQueueChart";
import { cn } from "@/components/ui";
import type { QueuePoint, WorkerRow } from "@/lib/health/types";
import { useAdminCelery } from "@/lib/hooks/useHealth";
import { useTranslations } from "next-intl";
import { DrawerPanel, DrawerStatCard } from "./drawer-parts";

/**
 * CeleryDashboard — the "Monitoring Panel / Dashboard" tab for the Celery drawer
 * (design frame 04): three KPI tiles, the queue-backlog line chart, and the
 * active-workers table.
 */
export function CeleryDashboard() {
  const t = useTranslations("health");
  const tc = useTranslations("health.celeryDrawer");
  const { data } = useAdminCelery();

  const series: QueuePoint[] = (data?.queue_backlog_series ?? []).map((p) => ({
    time: p.sampled_at.slice(11, 16), // Extract HH:MM.
    knowhere: p.knowhere ?? 0,
    pixelrag: p.pixelrag ?? 0,
  }));

  const workers: WorkerRow[] = (data?.worker_details ?? []).map((w) => ({
    name: w.name,
    pid: w.pid != null ? `pid ${w.pid}` : "—",
    state: w.state === "active" ? "busy" : "idle",
    current: w.current ?? "—",
    memory:
      w.memory == null
        ? "—"
        : w.memory < 1024
          ? `${w.memory} MB`
          : `${(w.memory / 1024).toFixed(1)} GB`,
  }));

  const nodes = data?.workers?.length ?? 0;
  const pending = data?.pending ?? 0;
  const succeeded = data?.succeeded ?? 0;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* KPI tiles */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard
          label={tc("stats.nodes.label")}
          value={nodes.toLocaleString()}
          sub={tc("stats.nodes.sub")}
        />
        <DrawerStatCard
          label={tc("stats.pending.label")}
          value={pending.toLocaleString()}
          tone={pending > 0 ? "danger" : "default"}
          sub={tc("stats.pending.sub")}
        />
        <DrawerStatCard
          label={tc("stats.succeeded.label")}
          value={succeeded.toLocaleString()}
          tone="success"
          sub={tc("stats.succeeded.sub")}
        />
      </div>

      {/* Queue backlog chart */}
      <DrawerPanel
        title={tc("queueTitle")}
        note={
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-2 w-2 rounded-full bg-[#0485F7]" />
              {tc("legend.knowhere")}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-2 w-2 rounded-full bg-[#7C5CF6]" />
              {tc("legend.pixelrag")}
            </span>
          </span>
        }
      >
        <HealthQueueChart data={series} />
      </DrawerPanel>

      {/* Active workers table */}
      <DrawerPanel
        title={tc("workers.title")}
        note={tc("workers.count", { n: workers.length })}
        bodyClassName="overflow-hidden rounded-xl border border-border"
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-(--surface-muted) text-left text-[11px] font-medium text-foreground-tertiary">
              <th className="px-3 py-2 font-medium">{tc("workers.cols.worker")}</th>
              <th className="px-3 py-2 font-medium">{tc("workers.cols.state")}</th>
              <th className="px-3 py-2 font-medium">{tc("workers.cols.current")}</th>
              <th className="px-3 py-2 text-right font-medium">{tc("workers.cols.memory")}</th>
            </tr>
          </thead>
          <tbody>
            {workers.map((w) => {
              const busy = w.state === "busy";
              return (
                <tr key={w.name} className="border-t border-border">
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col">
                      <span className="font-mono text-xs font-medium text-foreground">
                        {w.name}
                      </span>
                      <span className="font-mono text-[10px] text-foreground-tertiary">
                        {w.pid}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                        busy
                          ? "bg-success-soft text-success-soft-foreground"
                          : "bg-warning-soft text-warning-soft-foreground",
                      )}
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          busy ? "bg-success" : "bg-warning",
                        )}
                      />
                      {busy ? tc("workers.busy") : tc("workers.idle")}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-foreground-secondary">
                    {w.current === "—" ? t("common.na") : w.current}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs text-accent tabular-nums">
                    {w.memory}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </DrawerPanel>
    </div>
  );
}
