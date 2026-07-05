"use client";

import { cn } from "@/components/ui";
import type { CollectionRow } from "@/lib/health/types";
import { useAdminMinio, useAdminRedis } from "@/lib/hooks/useHealth";
import { useTranslations } from "next-intl";
import { CollectionAccordion } from "./CollectionAccordion";
import { DrawerPanel, DrawerStatCard } from "./drawer-parts";

/**
 * StorageDashboard — the "Monitoring Panel / Dashboard" tab for the combined MinIO &
 * Redis storage drawer. Renders two visually-separated sections (MinIO · Object
 * Storage, then Redis · Message Broker), each with its own 3-tile KPI grid and
 * a detail panel. MinIO buckets reuse CollectionAccordion; Redis INFO renders as
 * a key/value table.
 */
export function StorageDashboard() {
  const t = useTranslations("health");
  const ts = useTranslations("health.storageDrawer");
  const { data: minio } = useAdminMinio();
  const { data: redis } = useAdminRedis();

  // ----- MinIO bucket rows (reuses CollectionAccordion) -----
  const bucketRows: CollectionRow[] = (minio?.buckets ?? []).map((b) => {
    const created = b.creation_date ? b.creation_date.slice(0, 10) : "—";
    const metaParts = [`${ts("minio.meta.created")}: ${created}`];
    if (b.is_default) metaParts.push(ts("minio.meta.default"));
    return {
      name: b.name,
      tagKey: "storage",
      count: b.object_count != null ? b.object_count.toLocaleString() : "—",
      fields: [],
      meta: metaParts.join(" · "),
    };
  });

  const bucketCount = minio?.buckets?.length ?? 0;
  const defaultBucket = minio?.buckets?.find((b) => b.is_default);
  const objectCount = defaultBucket?.object_count ?? null;
  const endpoint = minio?.endpoint ?? "—";

  // ----- Redis info rows (key/value table) -----
  const info = redis?.info ?? null;
  const redisRows: Array<{ label: string; value: string }> = [
    {
      label: ts("redis.rows.version"),
      value: info?.version ?? "—",
    },
    {
      label: ts("redis.rows.uptime"),
      value: info?.uptime_days != null ? `${info.uptime_days} days` : "—",
    },
    {
      label: ts("redis.rows.role"),
      value: info?.role ?? "—",
    },
    {
      label: ts("redis.rows.clients"),
      value: info?.connected_clients != null ? info.connected_clients.toLocaleString() : "—",
    },
    {
      label: ts("redis.rows.usedMemory"),
      value: info?.used_memory_human ?? "—",
    },
    {
      label: ts("redis.rows.peakMemory"),
      value: info?.used_memory_peak_human ?? "—",
    },
    {
      label: ts("redis.rows.maxMemory"),
      value: info?.maxmemory_human && info.maxmemory_human !== "0" ? info.maxmemory_human : "—",
    },
  ];

  const clients = info?.connected_clients ?? null;
  const dbSize = redis?.db_size ?? null;
  const usedMemory = info?.used_memory_human ?? "—";

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* ===== MinIO · Object Storage ===== */}
      <SectionHeader dot="accent" title={ts("minio.sectionTitle")} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard
          label={ts("minio.stats.buckets.label")}
          value={bucketCount.toLocaleString()}
          sub={ts("minio.stats.buckets.sub")}
        />
        <DrawerStatCard
          label={ts("minio.stats.objects.label")}
          value={objectCount != null ? objectCount.toLocaleString() : "—"}
          tone={objectCount != null && objectCount > 0 ? "accent" : "default"}
          sub={ts("minio.stats.objects.sub")}
        />
        <DrawerStatCard
          label={ts("minio.stats.endpoint.label")}
          value={endpoint}
          tone="accent"
          sub={ts("minio.stats.endpoint.sub")}
        />
      </div>
      <DrawerPanel
        title={ts("minio.bucketsTitle")}
        note={ts("minio.bucketsCount", { n: bucketCount })}
      >
        {bucketRows.length > 0 ? (
          <CollectionAccordion
            rows={bucketRows}
            ns="storageDrawer"
            countLabel={(c) => ts("minio.objects", { n: c })}
          />
        ) : (
          <p className="py-6 text-center text-xs text-foreground-tertiary">
            {minio?.error ?? t("common.na")}
          </p>
        )}
      </DrawerPanel>

      {/* ===== Redis · Message Broker ===== */}
      <SectionHeader dot="warning" title={ts("redis.sectionTitle")} className="mt-2" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard
          label={ts("redis.stats.clients.label")}
          value={clients != null ? clients.toLocaleString() : "—"}
          sub={ts("redis.stats.clients.sub")}
        />
        <DrawerStatCard
          label={ts("redis.stats.dbSize.label")}
          value={dbSize != null ? dbSize.toLocaleString() : "—"}
          tone="accent"
          sub={ts("redis.stats.dbSize.sub")}
        />
        <DrawerStatCard
          label={ts("redis.stats.memory.label")}
          value={usedMemory}
          tone="accent"
          sub={ts("redis.stats.memory.sub")}
        />
      </div>
      <DrawerPanel title={ts("redis.infoTitle")} note={ts("redis.infoNote")}>
        <table className="w-full text-sm">
          <tbody>
            {redisRows.map((row) => (
              <tr key={row.label} className="border-b border-border last:border-b-0">
                <td className="px-3 py-2.5 text-xs font-medium text-foreground-tertiary">
                  {row.label}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-xs text-foreground tabular-nums">
                  {row.value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </DrawerPanel>
    </div>
  );
}

/** Compact section divider: colored dot + uppercase title. Keeps the two-service
 *  drawer visually structured without introducing a new shared component. */
function SectionHeader({
  dot,
  title,
  className,
}: {
  dot: "accent" | "warning";
  title: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span
        aria-hidden
        className={cn("h-2 w-2 rounded-full", dot === "accent" ? "bg-accent" : "bg-warning")}
      />
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-foreground-tertiary">
        {title}
      </h3>
    </div>
  );
}
