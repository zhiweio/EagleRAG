"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

/**
 * HealthHeaderActions — the right-aligned controls in the health page header
 * (design frame 03): an Online / Degraded legend and a Refresh button. Clicking
 * Refresh invalidates the health / admin / mcp-tools query caches so all polled
 * data is re-fetched, and plays a brief spin animation.
 */
export function HealthHeaderActions() {
  const t = useTranslations("health");
  const queryClient = useQueryClient();
  const [spinning, setSpinning] = useState(false);

  const onRefresh = () => {
    setSpinning(true);
    queryClient.invalidateQueries({ queryKey: ["health"] });
    queryClient.invalidateQueries({ queryKey: ["admin"] });
    queryClient.invalidateQueries({ queryKey: ["mcp-tools"] });
    setTimeout(() => setSpinning(false), 800);
  };

  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-3 text-xs text-foreground-secondary">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2 w-2 rounded-full bg-success" />
          {t("legend.online")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2 w-2 rounded-full bg-warning" />
          {t("legend.degraded")}
        </span>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-foreground-secondary transition-colors hover:bg-background-secondary"
      >
        <RefreshCw
          size={14}
          strokeWidth={2}
          aria-hidden
          className={spinning ? "animate-spin" : undefined}
        />
        {t("refresh")}
      </button>
    </div>
  );
}
