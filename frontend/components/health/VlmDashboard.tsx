"use client";

import { ICON_TONE } from "@/components/health/health-visuals";
import { useAdminVlm, useUpdateModelRouter } from "@/lib/hooks/useHealth";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ToggleSwitch } from "./ToggleSwitch";
import { DrawerPanel, DrawerStatCard } from "./drawer-parts";

const ROUTER_FE_KEYS = ["vlm", "textLlm", "embedding"] as const;
type RouterFeKey = (typeof ROUTER_FE_KEYS)[number];

/**
 * VlmDashboard — the "Monitoring Panel / Dashboard" tab for the models (VLM / LLM)
 * drawer (design frame 06): three KPI tiles and the model-router toggle list.
 */
export function VlmDashboard() {
  const tv = useTranslations("health.vlmDrawer");
  const { data } = useAdminVlm();
  const { mutate: updateMutate } = useUpdateModelRouter();

  const [routes, setRoutes] = useState<Record<string, boolean>>({
    vlm: true,
    textLlm: true,
    embedding: true,
  });

  // Sync backend model_router → routes state (on first load or after refresh).
  useEffect(() => {
    const routerRows = data?.model_router;
    if (!routerRows) return;
    setRoutes((prev) => {
      const next = { ...prev };
      for (const m of routerRows) {
        // Only handle known keys; filter out unexpected values.
        if (m.key !== "vlm" && m.key !== "text_llm" && m.key !== "embedding") continue;
        const feKey = m.key === "text_llm" ? "textLlm" : (m.key as RouterFeKey);
        next[feKey] = m.enabled ?? true;
      }
      return next;
    });
  }, [data?.model_router]);

  const latency = data?.latency != null ? `${(data.latency / 1000).toFixed(1)}s` : "—";
  const tokens = data?.tokens != null ? data.tokens.toLocaleString() : "—";
  const errorRate = data?.error_rate != null ? `${(data.error_rate * 100).toFixed(2)}%` : "—";

  const onChange = (feKey: RouterFeKey, next: boolean) => {
    setRoutes((prev) => ({ ...prev, [feKey]: next })); // Optimistic update.
    const payload =
      feKey === "vlm"
        ? { vlm: next }
        : feKey === "textLlm"
          ? { text_llm: next }
          : { embedding: next };
    updateMutate(payload);
  };

  const purple = ICON_TONE.purple;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard label={tv("stats.latency.label")} value={latency} tone="accent" />
        <DrawerStatCard label={tv("stats.tokens.label")} value={tokens} />
        <DrawerStatCard label={tv("stats.errorRate.label")} value={errorRate} tone="success" />
      </div>

      <DrawerPanel
        title={tv("routerTitle")}
        note={tv("routerNote")}
        bodyClassName="flex flex-col gap-2"
      >
        {ROUTER_FE_KEYS.map((feKey) => {
          const name = tv(`modelNames.${feKey}`);
          return (
            <div
              key={feKey}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3.5 py-3"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span
                  aria-hidden
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                  style={purple.style}
                >
                  <Sparkles size={15} strokeWidth={2} />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="font-mono text-xs font-medium text-foreground">{name}</span>
                  <span className="text-[11px] text-foreground-tertiary">
                    {tv(`models.${feKey}`)}
                  </span>
                </div>
              </div>
              <ToggleSwitch
                checked={routes[feKey] ?? true}
                onChange={(next) => onChange(feKey, next)}
                ariaLabel={name}
              />
            </div>
          );
        })}
      </DrawerPanel>
    </div>
  );
}
