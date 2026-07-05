"use client";

import { cn } from "@/components/ui";
import type { CollectionRow } from "@/lib/health/types";
import { useAdminMilvus, useMilvusClean, useMilvusFlush } from "@/lib/hooks/useHealth";
import { Eraser, HardDriveDownload } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { CollectionAccordion } from "./CollectionAccordion";
import { DrawerActionButton } from "./DrawerActionButton";
import { DrawerPanel, DrawerStatCard } from "./drawer-parts";

/**
 * MilvusDashboard — the "Monitoring Panel / Dashboard" tab for the Milvus / PixelRAG
 * drawer (design frame 05): three KPI tiles, the collection accordion, and the
 * maintenance action buttons.
 */
export function MilvusDashboard() {
  const tm = useTranslations("health.milvusDrawer");
  const { data } = useAdminMilvus();
  const flushMut = useMilvusFlush();
  const cleanMut = useMilvusClean();

  const [status, setStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showStatus = useCallback((type: "success" | "error", msg: string) => {
    setStatus({ type, msg });
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setStatus(null), 4000);
  }, []);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const runAction = (mut: typeof flushMut, label: string) => {
    mut.mutate(undefined, {
      onSuccess: (r) => showStatus("success", r.message || `${label}完成`),
      onError: (e) =>
        showStatus("error", `${label}失败: ${e instanceof Error ? e.message : String(e)}`),
    });
  };

  const rows: CollectionRow[] = (data?.collection_details ?? []).map((c) => ({
    name: c.name,
    tagKey: c.name.includes("visual") ? "visual" : "text",
    count: c.num_entities != null ? c.num_entities.toLocaleString() : "—",
    fields: [
      { labelKey: "dim", value: c.dim?.toString() ?? "—" },
      { labelKey: "metric", value: c.metric_type ?? "—" },
      { labelKey: "index", value: c.index_type ?? "—" },
    ],
    meta: `字段: ${c.fields?.map((f) => f.name).join(" · ") ?? ""}`,
  }));

  const collections = data?.collection_details?.length ?? 0;
  const indexSize = data?.index_size ?? "—";
  const memory = data?.memory != null ? data.memory.toFixed(1) : "—";

  const busy = flushMut.isPending || cleanMut.isPending;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard
          label={tm("stats.collections.label")}
          value={collections.toLocaleString()}
          sub={tm("stats.collections.sub")}
        />
        <DrawerStatCard
          label={tm("stats.indexSize.label")}
          value={indexSize}
          sub={tm("stats.indexSize.sub")}
        />
        <DrawerStatCard
          label={tm("stats.memory.label")}
          value={memory}
          tone="accent"
          sub={tm("stats.memory.sub")}
        />
      </div>

      <DrawerPanel title={tm("accordionTitle")} note={tm("count", { n: rows.length })}>
        <CollectionAccordion
          rows={rows}
          ns="milvusDrawer"
          countLabel={(c) => tm("entities", { n: c })}
        />
      </DrawerPanel>

      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <DrawerActionButton
            icon={Eraser}
            label={tm("actions.clean")}
            loading={cleanMut.isPending}
            disabled={busy}
            onClick={() => runAction(cleanMut, tm("actions.clean"))}
          />
          <DrawerActionButton
            icon={HardDriveDownload}
            label={tm("actions.flush")}
            loading={flushMut.isPending}
            disabled={busy}
            onClick={() => runAction(flushMut, tm("actions.flush"))}
          />
        </div>
        {status ? (
          <p
            className={cn(
              "text-xs font-medium",
              status.type === "success" ? "text-success" : "text-danger",
            )}
          >
            {status.msg}
          </p>
        ) : null}
      </div>
    </div>
  );
}
