"use client";

import { cn } from "@/components/ui";
import type { ProbeRowData, ResourceLimitData } from "@/lib/health/types";
import { useAdminConfig, useAdminProbes } from "@/lib/hooks/useHealth";
import { useTranslations } from "next-intl";
import { DrawerPanel, ProgressBar } from "./drawer-parts";

/**
 * ConfigProbesTab — the "Config & Probes" tab shared by every
 * service drawer (design frame 12): health probes list, resource-limit progress
 * bars, and a runtime config block.
 */
export function ConfigProbesTab() {
  const t = useTranslations("health.configProbes");
  const probesQuery = useAdminProbes();
  const configQuery = useAdminConfig();

  const pc = probesQuery.data?.probe_config ?? null;
  const probes: ProbeRowData[] = [
    { key: "liveness", timing: pc?.liveness ?? "—", status: "pass" },
    { key: "readiness", timing: pc?.readiness ?? "—", status: "pass" },
    { key: "startup", timing: pc?.startup ?? "—", status: "pass" },
  ];

  const rl = probesQuery.data?.resource_limits ?? null;
  const resources: ResourceLimitData[] = [];
  if (rl?.cpu) {
    resources.push({
      key: "cpu",
      used: rl.cpu.used.toFixed(1),
      limit: rl.cpu.limit?.toFixed(0) ?? "—",
      unit: rl.cpu.unit || "cores",
      percent: rl.cpu.percent ?? 0,
    });
  }
  if (rl?.memory) {
    resources.push({
      key: "memory",
      used: rl.memory.used.toFixed(1),
      limit: rl.memory.limit?.toFixed(0) ?? "—",
      unit: rl.memory.unit || "MB",
      percent: rl.memory.percent ?? 0,
    });
  }

  const configText = configQuery.data
    ? Object.entries(configQuery.data as Record<string, unknown>)
        .filter(([k]) => k !== "auth")
        .map(([k, v]) => {
          if (typeof v === "object" && v !== null) {
            return `[${k}]\n${Object.entries(v as Record<string, unknown>)
              .map(([sk, sv]) => `${sk} = ${JSON.stringify(sv)}`)
              .join("\n")}`;
          }
          return `${k} = ${JSON.stringify(v)}`;
        })
        .join("\n\n")
    : "Loading...";

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Health probes */}
      <DrawerPanel
        title={t("probesTitle")}
        note={t("probesCount", { n: probes.length })}
        bodyClassName="flex flex-col gap-2"
      >
        {probes.map((probe) => {
          const pass = probe.status === "pass";
          return (
            <div
              key={probe.key}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3.5 py-3"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span
                  aria-hidden
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    pass ? "bg-success" : "bg-warning",
                  )}
                />
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium text-foreground">
                    {t(`probes.${probe.key}.name`)}
                  </span>
                  <span className="text-[11px] text-foreground-tertiary">
                    {t(`probes.${probe.key}.sub`)}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="hidden flex-col items-end sm:flex">
                  <span className="font-mono text-xs text-foreground-secondary">
                    {probe.timing}
                  </span>
                  <span className="text-[10px] text-foreground-tertiary">{t("timingLegend")}</span>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
                    pass
                      ? "bg-success-soft text-success-soft-foreground"
                      : "bg-warning-soft text-warning-soft-foreground",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn("h-1.5 w-1.5 rounded-full", pass ? "bg-success" : "bg-warning")}
                  />
                  {pass ? t("pass") : t("degraded")}
                </span>
              </div>
            </div>
          );
        })}
      </DrawerPanel>

      {/* Resource limits */}
      <DrawerPanel
        title={t("resourcesTitle")}
        note={t("resourcesNote")}
        bodyClassName="flex flex-col gap-4"
      >
        {resources.map((res) => (
          <div key={res.key} className="flex flex-col gap-2">
            <div className="flex items-end justify-between gap-2">
              <div className="flex flex-col">
                <span className="text-sm font-medium text-foreground">
                  {t(`resources.${res.key}`)}
                </span>
                <span className="text-[11px] text-foreground-tertiary">{t("requestLimit")}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="font-mono text-sm font-semibold text-foreground tabular-nums">
                  {res.used} / {res.limit}
                </span>
                <span className="text-xs text-foreground-tertiary">{res.unit}</span>
                <span className="ml-1 text-xs font-medium text-accent">
                  {t("used", { percent: res.percent })}
                </span>
              </div>
            </div>
            <ProgressBar percent={res.percent} tone="accent" />
          </div>
        ))}
      </DrawerPanel>

      {/* Runtime config */}
      <DrawerPanel title={t("runtimeTitle")} note={t("runtimeFile")} bodyClassName="">
        <pre className="overflow-auto rounded-xl bg-background-inverse p-3 font-mono text-[11px] leading-relaxed text-foreground-inverse/90">
          {configText}
        </pre>
      </DrawerPanel>
    </div>
  );
}
