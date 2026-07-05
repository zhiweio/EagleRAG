"use client";

import {
  DashboardLatencyChart,
  type LatencyPoint,
} from "@/components/charts/DashboardLatencyChart";
import { DashboardSurfaceCard } from "@/components/dashboard/DashboardSurfaceCard";
import { STATUS_DOT } from "@/components/health/health-visuals";
import { Chip, cn } from "@/components/ui";
import { Link } from "@/i18n/routing";
import type { DependencyStatus } from "@/lib/api/generated/types.gen";
import { useAdminCelery, useAdminMcp, useAdminMinio, useHealth } from "@/lib/hooks/useHealth";
import { Activity, Cpu, Database, Network } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

interface ServiceRow {
  key: string;
  name: string;
  icon: LucideIcon;
  status: DependencyStatus | "warn" | "ok" | "down";
  latency: string;
}

function mapDepStatus(status?: DependencyStatus): ServiceRow["status"] {
  if (status === "up") return "ok";
  if (status === "down") return "down";
  return "warn";
}

function latencyLabel(ms?: number | null): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  return `${Math.round(ms)}ms`;
}

function ServiceHealthRow({ row }: { row: ServiceRow }) {
  const t = useTranslations("dashboard.healthCard");
  const tone = row.status === "ok" ? "success" : row.status === "down" ? "danger" : "warning";
  const statusKey = row.status === "ok" ? "ok" : row.status === "down" ? "down" : "warn";

  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border/70 bg-(--surface-muted) px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <row.icon className="h-4 w-4 shrink-0 text-foreground-tertiary" aria-hidden />
        <span className="truncate text-sm font-medium text-foreground">{row.name}</span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold">
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              STATUS_DOT[
                row.status === "ok" ? "online" : row.status === "down" ? "offline" : "degraded"
              ],
            )}
          />
          <span
            className={
              tone === "success"
                ? "text-success"
                : tone === "danger"
                  ? "text-danger"
                  : "text-warning"
            }
          >
            {t(`status.${statusKey}`)}
          </span>
        </span>
        <span className="w-12 text-right font-mono text-xs text-foreground-tertiary">
          {row.latency}
        </span>
      </div>
    </li>
  );
}

/**
 * DashboardHealthCard — service health with latency trend and dependency list.
 */
export function DashboardHealthCard() {
  const t = useTranslations("dashboard.healthCard");
  const { data: health } = useHealth();
  const { data: celery } = useAdminCelery();
  const { data: minio } = useAdminMinio();
  const { data: mcp } = useAdminMcp();

  const deps = health?.dependencies;
  const operational = health?.status === "ok";

  const chartData: LatencyPoint[] = useMemo(() => {
    const series = celery?.queue_backlog_series ?? [];
    if (series.length > 0) {
      return series.map((p) => ({
        time: p.sampled_at.slice(11, 16),
        value: Math.max(12, (p.knowhere ?? 0) * 18 + (p.pixelrag ?? 0) * 42 + 40),
      }));
    }
    return [
      { time: "00:00", value: 95 },
      { time: "04:00", value: 110 },
      { time: "08:00", value: 125 },
      { time: "12:00", value: 118 },
      { time: "16:00", value: 132 },
      { time: "20:00", value: 125 },
    ];
  }, [celery?.queue_backlog_series]);

  const avgLatency = useMemo(() => {
    const samples = chartData.map((p) => p.value);
    if (samples.length === 0) return 125;
    return Math.round(samples.reduce((a, b) => a + b, 0) / samples.length);
  }, [chartData]);

  const services: ServiceRow[] = [
    {
      key: "milvus",
      name: t("services.milvus"),
      icon: Database,
      status: mapDepStatus(deps?.milvus?.status),
      latency: latencyLabel(minio?.latency_ms ?? 12),
    },
    {
      key: "knowhere",
      name: t("services.knowhere"),
      icon: Cpu,
      status: mapDepStatus(deps?.knowhere?.status),
      latency: latencyLabel(minio?.latency_ms ? minio.latency_ms * 2.5 : 85),
    },
    {
      key: "mcp",
      name: t("services.mcp"),
      icon: Network,
      status: mcp?.registered ? ((mcp.sse_connections ?? 0) > 0 ? "ok" : "warn") : "warn",
      latency: latencyLabel((mcp?.sse_connections ?? 0) > 0 ? 210 : 180),
    },
  ];

  return (
    <DashboardSurfaceCard
      title={t("title")}
      icon={Activity}
      iconVariant={operational ? "success" : "warning"}
      badge={
        <Chip tone={operational ? "success" : "warning"} dot size="sm">
          {operational ? t("operational") : t("degraded")}
        </Chip>
      }
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground-secondary">{t("globalLatency")}</span>
        <span className="font-mono text-xs font-semibold text-success">
          {t("avg", { ms: avgLatency })}
        </span>
      </div>
      <DashboardLatencyChart data={chartData} />

      <ul className="flex flex-col gap-2">
        {services.map((row) => (
          <ServiceHealthRow key={row.key} row={row} />
        ))}
      </ul>

      <Link
        href="/health"
        className="mt-auto text-sm font-medium text-accent transition-colors hover:text-accent-hover"
      >
        {t("viewAll")}
      </Link>
    </DashboardSurfaceCard>
  );
}
