import { cn } from "@/components/ui";
import type { ServiceStatus } from "@/lib/health/types";
import { useTranslations } from "next-intl";

/**
 * Status badge (top-right of the drawer header).
 *
 * Display semantics switch with ``status``:
 * - ``online``  green bg + "Running · Uptime {uptime}" (keeps the original design semantics);
 * - ``offline`` red bg + "Offline" (replaces the uptime text to avoid misleading);
 * - ``unknown`` neutral grey bg + "Unknown / Not probed";
 * - ``degraded`` yellow bg + uptime text (partially healthy, still shows the duration).
 *
 * The previous version had no ``status`` param: a fixed green bg + running text,
 * decoupled from the backend status, which still showed green "Running" when the
 * service was down / not probed — highly misleading. Now it accepts a ``status``
 * prop that drives the palette and text, decided by the parent (``ServiceDrawer``)
 * based on the backend probe status.
 */
const PILL_STYLE: Record<ServiceStatus, { wrap: string; dot: string; showUptime: boolean }> = {
  online: {
    wrap: "bg-success-soft text-success-soft-foreground",
    dot: "bg-success",
    showUptime: true,
  },
  offline: {
    wrap: "bg-danger-soft text-danger-soft-foreground",
    dot: "bg-danger",
    showUptime: false,
  },
  unknown: {
    wrap: "bg-(--surface-muted) text-foreground-secondary",
    dot: "bg-foreground-tertiary",
    showUptime: false,
  },
  degraded: {
    wrap: "bg-warning-soft text-warning-soft-foreground",
    dot: "bg-warning",
    showUptime: true,
  },
};

export function StatusPill({
  status,
  uptime,
}: {
  status: ServiceStatus;
  /** Duration shown only for online/degraded; offline/unknown show the status label instead. */
  uptime?: string;
}) {
  const t = useTranslations("health.drawer");
  const style = PILL_STYLE[status];
  const label = style.showUptime
    ? t("running", { uptime: uptime || t("statusPill.running") })
    : t(`statusPill.${status === "offline" ? "offline" : "noProbe"}`);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        style.wrap,
      )}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
      {label}
    </span>
  );
}
