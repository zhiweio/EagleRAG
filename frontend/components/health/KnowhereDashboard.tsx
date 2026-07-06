"use client";

import { cn } from "@/components/ui";
import {
  kbPartitionTagKey,
  parserTmpPathFromDetail,
  resolveKnowhereMode,
} from "@/lib/health/knowhere-display";
import type { CollectionRow } from "@/lib/health/types";
import { useAdminKnowhere, useKnowhereClean, useKnowhereFlush } from "@/lib/hooks/useHealth";
import { Eraser, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { CollectionAccordion } from "./CollectionAccordion";
import { DrawerActionButton } from "./DrawerActionButton";
import { DrawerPanel, DrawerStatCard } from "./drawer-parts";

/**
 * KnowhereDashboard — the "Monitoring Panel / Dashboard" tab for the Knowhere drawer
 * (design frame 13): three KPI tiles, the knowledge-base partition accordion,
 * and the maintenance action buttons.
 */
export function KnowhereDashboard() {
  const tk = useTranslations("health.knowhereDrawer");
  const tm = useTranslations("health.milvusDrawer");
  const { data } = useAdminKnowhere();
  const flushMut = useKnowhereFlush();
  const cleanMut = useKnowhereClean();
  const mode = resolveKnowhereMode(data?.mode);

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
      onSuccess: (r) =>
        showStatus("success", r.message || tk("actions.success", { action: label })),
      onError: (e) =>
        showStatus(
          "error",
          tk("actions.error", {
            action: label,
            message: e instanceof Error ? e.message : String(e),
          }),
        ),
    });
  };

  const rows: CollectionRow[] = (data?.partitions ?? []).map((p) => ({
    name: p.kb_name,
    tagKey: kbPartitionTagKey(p.kb_name),
    count: String(p.document_count ?? 0),
    fields: [],
    meta: tk("partitionMeta", {
      documents: p.document_count ?? "—",
      chunks: p.chunk_count ?? "—",
    }),
  }));

  const parsed = data?.parsed != null ? data.parsed.toLocaleString() : "—";
  const chunks = data?.chunks != null ? data.chunks.toLocaleString() : "—";
  const tmpPath = parserTmpPathFromDetail(data?.detail);

  const runtimeStat =
    mode === "api"
      ? {
          label: tk("stats.runtimeApi.label"),
          value:
            data?.status === "up"
              ? tk("stats.runtimeApi.valueUp")
              : tk("stats.runtimeApi.valueDown"),
          sub: tk("stats.runtimeApi.sub", { url: data?.base_url ?? "—" }),
        }
      : {
          label: tk("stats.runtimeParser.label"),
          value: tk("stats.runtimeParser.value"),
          sub: tmpPath
            ? tk("stats.runtimeParser.sub", { path: tmpPath })
            : tk("stats.runtimeParser.subFallback"),
        };

  const busy = flushMut.isPending || cleanMut.isPending;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DrawerStatCard
          label={tk("stats.parsed.label")}
          value={parsed}
          sub={tk("stats.parsed.sub")}
        />
        <DrawerStatCard
          label={tk("stats.chunks.label")}
          value={chunks}
          sub={tk("stats.chunks.sub")}
        />
        <DrawerStatCard
          label={runtimeStat.label}
          value={runtimeStat.value}
          tone="accent"
          sub={runtimeStat.sub}
        />
      </div>

      <DrawerPanel title={tk("partitionsTitle")} note={tk("partitionCount", { n: rows.length })}>
        <CollectionAccordion
          rows={rows}
          ns="knowhereDrawer"
          countLabel={(c) => tk("documents", { n: c })}
        />
      </DrawerPanel>

      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <DrawerActionButton
            icon={RefreshCw}
            label={tm("actions.flush")}
            loading={flushMut.isPending}
            disabled={busy}
            onClick={() => runAction(flushMut, tm("actions.flush"))}
          />
          <DrawerActionButton
            icon={Eraser}
            label={tm("actions.clean")}
            loading={cleanMut.isPending}
            disabled={busy}
            onClick={() => runAction(cleanMut, tm("actions.clean"))}
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
