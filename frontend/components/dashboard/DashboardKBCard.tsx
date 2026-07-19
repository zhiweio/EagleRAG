"use client";

import { DashboardSurfaceCard } from "@/components/dashboard/DashboardSurfaceCard";
import { KBBadge } from "@/components/kb/kb-visuals";
import { Chip, IconBox, type IconBoxProps, cn } from "@/components/ui";
import { Link } from "@/i18n/routing";
import { useKBOverview, useKnowledgeBases } from "@/lib/hooks/useKB";
import type { KnowledgeBase } from "@/lib/kb/types";
import { FileStack, LibraryBig, ShieldAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

function estimateStorageGb(kb: KnowledgeBase): string {
  const gb = Math.max(0.1, kb.documents / 280 + kb.graphNodes / 50_000);
  return `${gb.toFixed(gb < 10 ? 1 : 0)} GB`;
}

function kbStatusTone(kb: KnowledgeBase): "success" | "accent" | "warning" {
  if (kb.activeIngestions > 0) return "accent";
  if (kb.status === "degraded" || kb.status === "offline") return "warning";
  return "success";
}

function kbStatusLabel(
  kb: KnowledgeBase,
  t: (key: "statusSyncing" | "statusDegraded" | "statusActive") => string,
): string {
  if (kb.activeIngestions > 0) return t("statusSyncing");
  if (kb.status === "degraded" || kb.status === "offline") return t("statusDegraded");
  return t("statusActive");
}

function SummaryStat({
  label,
  value,
  icon: Icon,
  iconVariant,
  valueTone,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  iconVariant: IconBoxProps["variant"];
  valueTone?: "warning";
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 sm:px-5">
      <IconBox icon={Icon} variant={iconVariant} size={34} iconSize={17} radius="lg" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-[10px] font-semibold tracking-wide text-foreground-tertiary uppercase">
          {label}
        </span>
        <span
          className={cn(
            "font-mono text-xl font-bold tabular-nums tracking-tight sm:text-2xl",
            valueTone === "warning" ? "text-warning" : "text-foreground",
          )}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

function SummaryStrip({
  totalDocs,
  activeTenants,
  storageAlerts,
  labels,
}: {
  totalDocs: number;
  activeTenants: number;
  storageAlerts: number;
  labels: { totalDocs: string; activeTenants: string; storageAlerts: string };
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-[0_1px_2px_0_rgba(0,0,0,0.03)]">
      <div className="grid grid-cols-1 divide-y divide-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <SummaryStat
          label={labels.totalDocs}
          value={totalDocs.toLocaleString()}
          icon={FileStack}
          iconVariant="accent-soft"
        />
        <SummaryStat
          label={labels.activeTenants}
          value={activeTenants}
          icon={LibraryBig}
          iconVariant="accent"
        />
        <SummaryStat
          label={labels.storageAlerts}
          value={storageAlerts}
          icon={ShieldAlert}
          iconVariant={storageAlerts > 0 ? "warning" : "surface"}
          valueTone={storageAlerts > 0 ? "warning" : undefined}
        />
      </div>
    </div>
  );
}

/**
 * DashboardKBCard — knowledge-base table for the current deployment domain (stats + KB list).
 */
export function DashboardKBCard() {
  const t = useTranslations("dashboard.kbCard");
  const { data: overview } = useKBOverview();
  const { data: listData } = useKnowledgeBases({ sort: "size", limit: 8 });

  const items = listData?.items ?? [];
  const totalDocs = overview?.totalDocuments ?? 0;
  const activeTenants = overview?.kbCount ?? 0;
  const storageAlerts = useMemo(
    () =>
      items.filter(
        (kb) => kb.activeIngestions > 0 || kb.status === "degraded" || kb.status === "offline",
      ).length,
    [items],
  );

  return (
    <DashboardSurfaceCard
      title={t("title")}
      icon={LibraryBig}
      iconVariant="accent"
      action={
        <Link
          href="/kb"
          className="inline-flex h-8 items-center rounded-lg border border-border bg-surface px-3 text-xs font-semibold text-foreground transition-colors hover:bg-background-secondary"
        >
          {t("manage")}
        </Link>
      }
    >
      <SummaryStrip
        totalDocs={totalDocs}
        activeTenants={activeTenants}
        storageAlerts={storageAlerts}
        labels={{
          totalDocs: t("totalDocs"),
          activeTenants: t("activeTenants"),
          storageAlerts: t("storageAlerts"),
        }}
      />

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="grid grid-cols-[minmax(0,1.4fr)_88px_88px_96px] gap-2 border-b border-border/70 px-3 py-2 text-[10px] font-semibold tracking-wide text-foreground-tertiary uppercase">
          <span>{t("colTenant")}</span>
          <span className="text-right">{t("colStorage")}</span>
          <span className="text-right">{t("colDocuments")}</span>
          <span className="text-right">{t("colStatus")}</span>
        </div>
        <ul className="max-h-[220px] overflow-y-auto">
          {items.length === 0 ? (
            <li className="px-3 py-8 text-center text-sm text-foreground-tertiary">{t("empty")}</li>
          ) : (
            items.map((kb) => (
              <li
                key={kb.kbName}
                className="grid grid-cols-[minmax(0,1.4fr)_88px_88px_96px] items-center gap-2 border-b border-border/60 px-3 py-2.5 last:border-0"
              >
                <Link
                  href={`/kb/${encodeURIComponent(kb.kbName)}`}
                  className="flex min-w-0 items-center gap-2 transition-colors hover:text-accent"
                >
                  <KBBadge theme={kb.theme} icon={kb.icon} size={28} iconSize={14} />
                  <span className="truncate text-sm font-medium text-foreground">
                    {kb.displayName}
                  </span>
                </Link>
                <span className="text-right font-mono text-xs text-foreground-secondary">
                  {estimateStorageGb(kb)}
                </span>
                <span className="text-right font-mono text-xs text-foreground">
                  {kb.documents.toLocaleString()}
                </span>
                <span className="flex justify-end">
                  <Chip tone={kbStatusTone(kb)} size="sm">
                    {kbStatusLabel(kb, t)}
                  </Chip>
                </span>
              </li>
            ))
          )}
        </ul>
      </div>

      {storageAlerts > 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-warning">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("alertHint", { count: storageAlerts })}
        </p>
      ) : null}
    </DashboardSurfaceCard>
  );
}
