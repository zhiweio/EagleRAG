"use client";

import { DashboardSurfaceCard } from "@/components/dashboard/DashboardSurfaceCard";
import { documentName, normalizeStatus, progressPercent } from "@/components/ingest/status";
import { FileBadge } from "@/components/kb/kb-visuals";
import { Chip, cn } from "@/components/ui";
import { Link } from "@/i18n/routing";
import { useHealth } from "@/lib/hooks/useHealth";
import { useTasks } from "@/lib/hooks/useIngest";
import type { Task } from "@/lib/types";
import { Check, CloudUpload, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

function IngestFileRow({ task }: { task: Task }) {
  const phase = normalizeStatus(task.status);
  const pct = progressPercent(task);
  const name = documentName(task);
  const done = phase === "success";
  const running = phase === "running" || phase === "pending";
  const failed = phase === "failed";

  return (
    <li
      className={cn(
        "flex flex-col gap-1.5 px-3 py-2.5 transition-colors",
        running && "bg-accent-soft/25",
        failed && "bg-danger-soft/20",
      )}
    >
      <div className="flex items-center gap-2">
        <FileBadge name={name} size={14} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-snug text-foreground">
          {name}
        </span>
        {done ? (
          <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
        ) : running ? (
          <Loader2
            className="h-3.5 w-3.5 shrink-0 animate-spin text-accent motion-reduce:animate-none"
            aria-hidden
          />
        ) : null}
      </div>
      <div className="flex items-center gap-2 pl-6">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-border/50">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none",
              done
                ? "bg-success"
                : failed
                  ? "bg-danger"
                  : running
                    ? "bg-accent"
                    : "bg-foreground-tertiary/30",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-8 shrink-0 text-right font-mono text-[10px] text-foreground-tertiary">
          {pct}%
        </span>
      </div>
    </li>
  );
}

/**
 * DashboardIngestCard — live ingestion routing preview with task progress rows.
 */
export function DashboardIngestCard() {
  const t = useTranslations("dashboard.ingestCard");
  const { data } = useTasks({ limit: 20 });
  const { data: health } = useHealth();

  const tasks = useMemo(() => {
    const items = data?.items ?? [];
    const active = items.filter((task) => {
      const p = normalizeStatus(task.status);
      return p === "running" || p === "pending";
    });
    const recent = items.filter((task) => normalizeStatus(task.status) === "success");
    const picked = [...active, ...recent].slice(0, 3);
    return picked.length > 0 ? picked : items.slice(0, 3);
  }, [data?.items]);

  const knowhereUp = health?.dependencies?.knowhere?.status === "up";

  return (
    <DashboardSurfaceCard
      title={t("title")}
      icon={CloudUpload}
      iconVariant="success"
      badge={
        <Chip tone={knowhereUp ? "success" : "danger"} dot size="sm">
          {knowhereUp ? t("knowhereActive") : t("knowhereUnavailable")}
        </Chip>
      }
    >
      {tasks.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-3 py-8 text-center text-sm text-foreground-tertiary">
          {t("empty")}
        </p>
      ) : (
        <ul className="overflow-hidden rounded-xl border border-border divide-y divide-border/60">
          {tasks.map((task) => (
            <IngestFileRow key={task.job_id} task={task} />
          ))}
        </ul>
      )}

      <Link
        href="/ingest"
        className="mt-auto text-sm font-medium text-accent transition-colors hover:text-accent-hover"
      >
        {t("viewAll")}
      </Link>
    </DashboardSurfaceCard>
  );
}
