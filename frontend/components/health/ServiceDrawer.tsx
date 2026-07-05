"use client";

import { ICON_TONE } from "@/components/health/health-visuals";
import { cn } from "@/components/ui";
import type { DrawerKind, DrawerMeta, ServiceStatus } from "@/lib/health/types";
import { useHealth } from "@/lib/hooks/useHealth";
import { Drawer } from "@heroui/react";
import { Boxes, Cpu, Database, type LucideIcon, Server, Sparkles, Workflow, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { CeleryDashboard } from "./CeleryDashboard";
import { ConfigProbesTab } from "./ConfigProbesTab";
import { KnowhereDashboard } from "./KnowhereDashboard";
import { LiveLogsTab } from "./LiveLogsTab";
import { McpServerDashboard } from "./McpServerDashboard";
import { MilvusDashboard } from "./MilvusDashboard";
import { StatusPill } from "./StatusPill";
import { StorageDashboard } from "./StorageDashboard";
import { VlmDashboard } from "./VlmDashboard";

type TabKey = "dashboard" | "logs" | "config";
const TABS: TabKey[] = ["dashboard", "logs", "config"];

const DASHBOARDS: Record<DrawerKind, () => React.ReactNode> = {
  celery: () => <CeleryDashboard />,
  milvus: () => <MilvusDashboard />,
  vlm: () => <VlmDashboard />,
  mcp: () => <McpServerDashboard />,
  knowhere: () => <KnowhereDashboard />,
  storage: () => <StorageDashboard />,
};

// Static UI config (icon/tone never change; uptime is filled dynamically)
const DRAWER_META_STATIC: Record<DrawerKind, { icon: LucideIcon; tone: DrawerMeta["tone"] }> = {
  celery: { icon: Cpu, tone: "accent" },
  milvus: { icon: Boxes, tone: "accent" },
  vlm: { icon: Sparkles, tone: "purple" },
  mcp: { icon: Server, tone: "accent" },
  knowhere: { icon: Workflow, tone: "accent" },
  storage: { icon: Database, tone: "warning" },
};

// drawer kind → probe key in /health dependencies (null means no matching probe)
const DRAWER_DEP_KEY: Record<DrawerKind, string | null> = {
  celery: "celery",
  milvus: "milvus",
  vlm: "vlm",
  mcp: null,
  knowhere: "knowhere",
  // The storage drawer aggregates the minio + redis deps; its status is derived in the storage branch below.
  storage: null,
};

/** Map a backend DependencyStatus to a frontend ServiceStatus (matches ServiceGrid.mapStatus). */
function mapDepStatus(status: string | undefined): ServiceStatus {
  if (status === "up") return "online";
  if (status === "down") return "offline";
  if (status === "unknown") return "unknown";
  return "degraded";
}

/**
 * ServiceDrawer — the unified right-side drawer opened by the service cards
 * (design frames 04–13). One shell renders a per-kind dashboard plus the shared
 * live-logs and config-&-probes tabs. Controlled via `kind` / `onClose`.
 */
export function ServiceDrawer({ kind, onClose }: { kind: DrawerKind | null; onClose: () => void }) {
  const t = useTranslations("health.drawer");
  const [tab, setTab] = useState<TabKey>("dashboard");

  // Reset to the dashboard tab whenever a new service drawer is opened.
  useEffect(() => {
    if (kind) setTab("dashboard");
  }, [kind]);

  const { data } = useHealth();
  const deps = data?.dependencies;
  const cfg = kind ? DRAWER_META_STATIC[kind] : null;
  const depKey = kind ? DRAWER_DEP_KEY[kind] : null;
  const depStatus = depKey ? deps?.[depKey]?.status : undefined;
  const depUptime = depKey ? deps?.[depKey]?.uptime : undefined;
  // The storage drawer aggregates the minio + redis deps (matches the ServiceGrid card aggregation):
  // any down → offline; any non-up → degraded; both up → online.
  // Other drawers without a matching probe (mcp) default to online (green Running).
  let drawerStatus: ServiceStatus;
  let pillUptime: string | undefined;
  if (kind === "storage") {
    const minioStatus = deps?.minio?.status;
    const redisStatus = deps?.redis?.status;
    const statuses = [minioStatus, redisStatus];
    if (statuses.some((s) => s === "down")) {
      drawerStatus = "offline";
    } else if (statuses.some((s) => s !== "up")) {
      drawerStatus = "degraded";
    } else {
      drawerStatus = "online";
    }
    // Both start counting at API startup, so uptimes are roughly equal; shown only when both are up.
    const minioUp = deps?.minio?.uptime ?? "";
    const redisUp = deps?.redis?.uptime ?? "";
    pillUptime = minioUp && redisUp ? minioUp : undefined;
  } else {
    drawerStatus = !depKey ? "online" : mapDepStatus(depStatus);
    pillUptime = depStatus === "up" ? depUptime : undefined;
  }
  const meta: DrawerMeta | null = cfg ? { icon: cfg.icon, tone: cfg.tone } : null;
  const tone = meta ? ICON_TONE[meta.tone] : null;
  const Icon = meta?.icon;

  return (
    <Drawer
      isOpen={kind !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Drawer.Backdrop className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
        <Drawer.Content
          placement="right"
          className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
        >
          <Drawer.Dialog className="w-full !max-w-none sm:w-2/3 sm:!max-w-[1280px] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
            {kind && meta && Icon ? (
              <>
                <Drawer.Header className="flex flex-col gap-3 border-b border-border">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span
                        aria-hidden
                        className={cn(
                          "flex h-10 w-10 items-center justify-center rounded-xl",
                          tone?.className,
                        )}
                        style={tone?.style}
                      >
                        <Icon size={18} strokeWidth={2} />
                      </span>
                      <div className="flex flex-col">
                        <Drawer.Heading className="text-base font-semibold text-foreground">
                          {t(`titles.${kind}`)}
                        </Drawer.Heading>
                        <span className="text-xs text-foreground-tertiary">
                          {t(`subtitles.${kind}`)}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusPill status={drawerStatus} uptime={pillUptime} />
                      <Drawer.CloseTrigger
                        aria-label={t("close")}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-foreground-tertiary transition-colors hover:bg-background-secondary hover:text-foreground"
                      >
                        <X size={16} strokeWidth={2} aria-hidden />
                      </Drawer.CloseTrigger>
                    </div>
                  </div>

                  {/* Tab bar */}
                  <div className="flex items-center gap-1 -mb-px">
                    {TABS.map((tk) => {
                      const active = tab === tk;
                      return (
                        <button
                          key={tk}
                          type="button"
                          onClick={() => setTab(tk)}
                          className={cn(
                            "relative px-3 py-2 text-sm font-medium transition-colors",
                            active
                              ? "text-accent"
                              : "text-foreground-tertiary hover:text-foreground",
                          )}
                        >
                          {t(`tabs.${tk}`)}
                          {active ? (
                            <span
                              aria-hidden
                              className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
                            />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </Drawer.Header>

                <Drawer.Body className="bg-background p-0">
                  {tab === "dashboard" ? DASHBOARDS[kind]() : null}
                  {tab === "logs" ? <LiveLogsTab /> : null}
                  {tab === "config" ? <ConfigProbesTab /> : null}
                </Drawer.Body>
              </>
            ) : null}
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
