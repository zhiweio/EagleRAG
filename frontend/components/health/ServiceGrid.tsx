"use client";

import type { DependencyStatus } from "@/lib/api/generated/types.gen";
import type { DrawerKind, ServiceCardData, ServiceStatus } from "@/lib/health/types";
import { useHealth } from "@/lib/hooks/useHealth";
import { Cpu, Database, Layers, type LucideIcon, ScanLine, Sparkles, Workflow } from "lucide-react";
import { useState } from "react";
import { ServiceCard } from "./ServiceCard";
import { ServiceDrawer } from "./ServiceDrawer";

// Static UI config (icon/tone/i18nKey/drawer never change; status/chips/uptime derive from useHealth)
const CARD_CONFIG: Array<{
  kind: ServiceCardData["kind"];
  i18nKey: string;
  icon: LucideIcon;
  tone: ServiceCardData["tone"];
  drawer: DrawerKind | null;
  depKey: string;
}> = [
  {
    kind: "storage",
    i18nKey: "storage",
    icon: Database,
    tone: "warning",
    drawer: "storage",
    depKey: "minio",
  },
  {
    kind: "knowhere",
    i18nKey: "knowhere",
    icon: Workflow,
    tone: "accent",
    drawer: "knowhere",
    depKey: "knowhere",
  },
  {
    kind: "celery",
    i18nKey: "celery",
    icon: Cpu,
    tone: "accent",
    drawer: "celery",
    depKey: "celery",
  },
  {
    kind: "milvus",
    i18nKey: "milvus",
    icon: Layers,
    tone: "accent",
    drawer: "milvus",
    depKey: "milvus",
  },
  {
    kind: "pixelrag",
    i18nKey: "pixelrag",
    icon: ScanLine,
    tone: "purple",
    drawer: "milvus",
    depKey: "pixelrag",
  },
  {
    kind: "models",
    i18nKey: "models",
    icon: Sparkles,
    tone: "purple",
    drawer: "vlm",
    depKey: "vlm",
  },
];

function mapStatus(status: DependencyStatus | undefined): ServiceStatus {
  // Semantic mapping from backend DependencyStatus (3-state) to frontend ServiceStatus:
  // up → online (green) / down → offline (red) / unknown → unknown (neutral gray;
  // distinct from degraded; used when VLM isn't actively probed, pixelrag optional dep disabled, etc.).
  if (status === "up") return "online";
  if (status === "down") return "offline";
  if (status === "unknown") return "unknown";
  return "degraded"; // Fallback: undefined or future unknown states render as degraded.
}

/** Convert the detail string into 1-2 chips. E.g. "collections=2" → "Collections: 2". */
function chipsFromDetail(detail: string | undefined): ServiceCardData["chips"] {
  if (!detail) return [];
  const pairs = detail
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^([a-zA-Z_]+)=(.+)$/);
      if (!m) return null;
      const key = m[1].charAt(0).toUpperCase() + m[1].slice(1);
      return { label: `${key}: ${m[2].trim()}`, tone: "accent" as const };
    })
    .filter((x): x is { label: string; tone: "accent" } => x !== null);
  if (pairs.length) return pairs.slice(0, 2);
  return [{ label: detail.length > 30 ? detail.slice(0, 30) : detail, tone: "accent" }];
}

/**
 * ServiceGrid — the main service card grid (design frame 03). Renders six
 * service cards derived from `useHealth()` (GET /health). Clicking a card with
 * an associated drawer opens the unified ServiceDrawer. Drawer state is local.
 */
export function ServiceGrid() {
  const [drawerKind, setDrawerKind] = useState<DrawerKind | null>(null);
  const { data } = useHealth();
  const deps = data?.dependencies;

  const cards: ServiceCardData[] = CARD_CONFIG.map((cfg) => {
    const { kind, i18nKey, icon, tone, drawer, depKey } = cfg;
    // loading / error: render a placeholder card when data isn't ready (status=online, no chips)
    if (!deps) {
      return {
        kind,
        i18nKey,
        icon,
        tone,
        drawer,
        status: "online",
        chips: [],
        uptime: "—",
      };
    }
    // The storage card represents the combined minio + redis status; uptime is the shorter of the two (shown only when both are up)
    if (kind === "storage") {
      const statuses: Array<DependencyStatus | undefined> = [
        deps.minio?.status,
        deps.redis?.status,
      ];
      const status: ServiceStatus = statuses.some((s) => s === "down")
        ? "offline"
        : statuses.some((s) => s !== "up")
          ? "degraded"
          : "online";
      const chips = [
        ...chipsFromDetail(deps.minio?.detail),
        ...chipsFromDetail(deps.redis?.detail),
      ].slice(0, 2);
      // Both start counting at API startup, so uptimes are roughly equal; if either is down, show "—".
      const minioUp = deps.minio?.uptime ?? "";
      const redisUp = deps.redis?.uptime ?? "";
      const uptime = minioUp && redisUp ? minioUp : "—";
      return { kind, i18nKey, icon, tone, drawer, status, chips, uptime };
    }
    const dep = deps[depKey];
    return {
      kind,
      i18nKey,
      icon,
      tone,
      drawer,
      status: mapStatus(dep?.status),
      chips: chipsFromDetail(dep?.detail),
      uptime: dep?.uptime || "—",
    };
  });

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <ServiceCard
            key={card.kind}
            data={card}
            onOpen={card.drawer ? () => setDrawerKind(card.drawer) : undefined}
          />
        ))}
      </div>

      <ServiceDrawer kind={drawerKind} onClose={() => setDrawerKind(null)} />
    </>
  );
}
