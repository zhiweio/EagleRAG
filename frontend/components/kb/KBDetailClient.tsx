"use client";

import { TaskLogsModal } from "@/components/ingest/TaskLogsModal";
import { TaskTable } from "@/components/ingest/TaskTable";
import { Link, useRouter } from "@/i18n/routing";
import { useDeleteDocument, useDocuments } from "@/lib/hooks/useDocuments";
import { errorMessage, useDeleteTask, useRetryTask, useTasks } from "@/lib/hooks/useIngest";
import {
  useDeleteKB,
  useKBCollections,
  useKBFormatDistribution,
  useKBIngestionVolume,
  useKnowledgeBase,
  useRebuildKB,
} from "@/lib/hooks/useKB";
import { prefetchPreviewResource } from "@/lib/hooks/usePreviewResource";
import { useKBStore } from "@/lib/stores/kbStore";
import { usePreviewStore } from "@/lib/stores/previewStore";
import type { Document, Task } from "@/lib/types";
import { Button, Card } from "@heroui/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  Database,
  FileText,
  Image as ImageIcon,
  RefreshCw,
  Search,
  Settings2,
  Share2,
  Trash2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useMemo, useState } from "react";
import { DocumentDeleteModal } from "./DocumentDeleteModal";
import { EditKBDrawer } from "./EditKBDrawer";
import { KBDocumentsTable } from "./KBDocumentsTable";
import { KBToastProvider, useKBToast } from "./KBToast";
import { KpiCard, type KpiDef } from "./KpiCard";
import { MilvusCollectionCard } from "./MilvusCollectionCard";
import { PurgeConfirmModal } from "./PurgeConfirmModal";
import { RebuildConfirmModal } from "./RebuildConfirmModal";
import { FormatDonut, VolumeBars, chartPanelMinHeight } from "./kb-charts";
import { KBBadge, STATUS_STYLES } from "./kb-visuals";

type TabKey = "documents" | "logs" | "maintenance";

function Panel({
  title,
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`flex flex-col gap-4 rounded-2xl border border-border bg-surface p-5 shadow-[0_2px_8px_0_rgba(0,0,0,0.04)] ${className ?? ""}`.trim()}
    >
      {title ? <h2 className="shrink-0 text-sm font-semibold text-foreground">{title}</h2> : null}
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}

export function KBDetailClient({ kbName }: { kbName: string }) {
  return (
    <KBToastProvider>
      <KBDetailInner kbName={kbName} />
    </KBToastProvider>
  );
}

function KBDetailInner({ kbName }: { kbName: string }) {
  const t = useTranslations("kb.detail");
  const tToast = useTranslations("kb.toast");
  const locale = useLocale();
  const router = useRouter();
  const { pushToast } = useKBToast();
  const { setKbName } = useKBStore();
  const openPreview = usePreviewStore((s) => s.openPreview);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>("documents");
  const [editOpen, setEditOpen] = useState(false);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeError, setPurgeError] = useState<Error | null>(null);
  const [logsTask, setLogsTask] = useState<Task | null>(null);
  const [docToDelete, setDocToDelete] = useState<Document | null>(null);
  const [docPage, setDocPage] = useState(1);
  const [docPageSize, setDocPageSize] = useState(10);
  const [logPage, setLogPage] = useState(1);
  const [logPageSize, setLogPageSize] = useState(10);

  const { data: kb, isLoading } = useKnowledgeBase(kbName);
  const { data: segments = [] } = useKBFormatDistribution(kbName);
  const { data: volume } = useKBIngestionVolume(kbName);
  const { data: collections = [] } = useKBCollections(kbName);

  const docParams = useMemo(
    () => ({
      kb_name: kbName,
      limit: docPageSize,
      offset: (docPage - 1) * docPageSize,
    }),
    [kbName, docPage, docPageSize],
  );
  const taskParams = useMemo(
    () => ({
      kb_name: kbName,
      limit: logPageSize,
      offset: (logPage - 1) * logPageSize,
    }),
    [kbName, logPage, logPageSize],
  );

  const docsQuery = useDocuments(docParams);
  const tasksQuery = useTasks(taskParams, {
    enabled: tab === "logs",
    refetchInterval: tab === "logs" ? 5000 : false,
  });
  const rebuild = useRebuildKB();
  const deleteKB = useDeleteKB();
  const deleteDoc = useDeleteDocument();
  const retryTask = useRetryTask();
  const deleteTask = useDeleteTask();

  if (isLoading) {
    return <p className="py-20 text-center text-sm text-foreground-tertiary">{t("loading")}</p>;
  }

  if (!kb) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-border py-20 text-center">
        <p className="text-sm text-foreground-tertiary">
          {t("notFound")}: <span className="font-mono">{kbName}</span>
        </p>
        <Link
          href="/kb"
          className="rounded-lg bg-background-secondary px-4 py-2 text-sm font-medium text-foreground"
        >
          {t("back")}
        </Link>
      </div>
    );
  }

  const points = volume?.points ?? [];
  const documents = docsQuery.data?.items ?? [];
  const docTotal = docsQuery.data?.total ?? documents.length;
  const tasks = tasksQuery.data?.items ?? [];
  const taskTotal = tasksQuery.data?.total ?? tasks.length;

  const runRebuild = () => {
    setRebuildOpen(true);
  };

  const confirmRebuild = () => {
    rebuild.mutate(kbName, {
      onSuccess: (data) => {
        setRebuildOpen(false);
        pushToast({ variant: "success", title: tToast("rebuildStarted") });
        setLogsTask({
          job_id: data.job_id,
          status: "pending",
          pipeline: "rebuild",
          kb_name: kbName,
        } as Task);
      },
    });
  };

  const runPurge = () => {
    setPurgeError(null);
    setPurgeOpen(true);
  };

  const confirmPurge = () => {
    setPurgeError(null);
    deleteKB.mutate(kbName, {
      onSuccess: () => {
        setPurgeOpen(false);
        pushToast({ variant: "success", title: tToast("purgeSuccess") });
        router.push("/kb");
      },
      onError: (err) => {
        setPurgeError(err);
      },
    });
  };

  const goToIngest = () => {
    setKbName(kbName);
    router.push("/ingest");
  };

  const confirmDeleteDoc = () => {
    if (!docToDelete) return;
    const docId = docToDelete.document_id;
    deleteDoc.mutate(docId, {
      onSuccess: () => {
        pushToast({ variant: "success", title: tToast("docDeleted") });
        setDocToDelete(null);
      },
      onError: (err) => {
        pushToast({
          variant: "error",
          title: tToast("error"),
          description: err instanceof Error ? err.message : tToast("errorDesc"),
        });
      },
    });
  };
  const COLOR_MAP: Record<string, string> = {
    blue: "#3B82F6",
    violet: "#A855F7",
    emerald: "#10B981",
    amber: "#FBBF24",
  };
  const resolveSegmentColor = (color: string) =>
    color.startsWith("#") ? color : (COLOR_MAP[color] ?? "#888");
  const FORMAT_LABEL_BY_KEY: Record<string, string> = {
    pdf_text: t("format.pdfText"),
    pdf_scan: t("format.pdfScan"),
    docx: t("format.docx"),
    pptx: t("format.pptx"),
    xlsx: t("format.xlsx"),
    csv: t("format.csv"),
    md: t("format.md"),
    txt: t("format.txt"),
    json: t("format.json"),
    web: t("format.html"),
    image: t("format.image"),
    other: t("format.other"),
  };
  const chartSegments = segments.map((s) => ({
    key: String(s.key ?? ""),
    label: FORMAT_LABEL_BY_KEY[String(s.key)] ?? String(s.label),
    value: Number(s.value),
    color: resolveSegmentColor(String(s.color)),
  }));
  // The backend volume.label is a Chinese weekday; reformat via the ISO date for the current locale to stay bilingual.
  const weekdayFmt = new Intl.DateTimeFormat(locale === "en" ? "en-US" : "zh-CN", {
    weekday: "short",
  });
  const volumePoints = points.map((p) => {
    let label = String(p.label);
    const dateStr = (p as { date?: string }).date;
    if (dateStr) {
      const d = new Date(dateStr);
      if (!Number.isNaN(d.getTime())) label = weekdayFmt.format(d);
    }
    return { label, value: Number(p.value) };
  });
  const chartPanelClass = `h-full ${chartPanelMinHeight(chartSegments.length)}`;
  const storageCards = collections.map((c) => {
    const isVisual = c.name === "eagle_visual";
    return {
      name: String(c.name),
      dim: Number(c.dim),
      index: String(c.index),
      entities: Number(c.entities),
      capacityPct: Number(c.capacity_ratio ?? 0) * 100,
      isVisual,
      desc: isVisual ? t("storage.visualDesc") : t("storage.textDesc"),
      model: String(c.model ?? ""),
    };
  });

  const kpis: KpiDef[] = [
    {
      icon: FileText,
      color: "#0485F7",
      soft: "#0485F726",
      value: kb.documents,
      caption: t("kpi.docs"),
    },
    {
      icon: Share2,
      color: "#2563EB",
      soft: "#DBEAFE",
      value: kb.graphNodes,
      caption: t("kpi.nodes"),
    },
    {
      icon: ImageIcon,
      color: "#7C3AED",
      soft: "#EDE9FE",
      value: kb.visualSlices,
      caption: t("kpi.slices"),
    },
    {
      icon: Search,
      color: "#059669",
      soft: "#D1FAE5",
      value: kb.queries7d,
      caption: t("kpi.queries"),
    },
  ];

  const statusKey = kb.status ?? "online";
  const statusStyle = STATUS_STYLES[statusKey] ?? STATUS_STYLES.online;
  const statusLabel =
    statusKey === "offline"
      ? t("statusOffline")
      : statusKey === "degraded"
        ? t("statusDegraded")
        : t("statusOnline");

  const tabs: { key: TabKey; label: string }[] = [
    { key: "documents", label: t("tabs.documents") },
    { key: "logs", label: t("tabs.logs") },
    { key: "maintenance", label: t("tabs.maintenance") },
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Overview header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3.5">
          <KBBadge theme={kb.theme} icon={kb.icon} size={44} iconSize={22} radius={8} />
          <div className="flex flex-col gap-[3px]">
            <h1 className="text-[26px] font-semibold leading-tight text-foreground">
              {kb.displayName}
            </h1>
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="font-mono text-[13px] text-foreground-tertiary">
                {t("kbNamePrefix")}
                {kb.kbName}
              </span>
              {kb.description ? (
                <>
                  <span className="text-[13px] text-foreground-tertiary" aria-hidden>
                    ·
                  </span>
                  <span className="text-[13px] text-foreground-secondary">{kb.description}</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2.5">
          <span
            className="flex items-center gap-[7px] rounded-full px-[13px] py-1.5 text-xs font-semibold"
            style={{ backgroundColor: statusStyle.bg, color: statusStyle.fg }}
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: statusStyle.dot }}
              aria-hidden
            />
            {statusLabel}
          </span>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setEditOpen(true)}
              className="flex h-[42px] items-center gap-2 rounded-xl border border-border bg-surface px-3.5 text-[13px] font-medium text-foreground transition-colors hover:bg-(--surface-muted)"
            >
              <Settings2 className="h-[15px] w-[15px] text-foreground-secondary" aria-hidden />
              {t("config")}
            </button>
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-5 xl:grid-cols-4">
        {kpis.map((k) => (
          <KpiCard key={k.caption} {...k} />
        ))}
      </div>

      {/* Charts — equal-height cards; stats footers align at bottom */}
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-2">
        <Panel title={t("format.title")} className={chartPanelClass}>
          <FormatDonut
            segments={chartSegments}
            centerValue={kb.documents.toLocaleString()}
            centerLabel={t("kpi.docs").split("·")[0].trim()}
          />
        </Panel>
        <Panel title={t("volume.title")} className={chartPanelClass}>
          <VolumeBars points={volumePoints} />
        </Panel>
      </div>

      {/* Milvus storage */}
      <div className="flex flex-col gap-3.5">
        <div className="flex items-center gap-2">
          <Database className="h-[17px] w-[17px] text-foreground-secondary" aria-hidden />
          <h2 className="text-[15px] font-semibold text-foreground">{t("storage.title")}</h2>
        </div>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {storageCards.map((c) => {
            const chipBg = c.isVisual ? "#EDE9FE" : "#0485F726";
            const chipFg = c.isVisual ? "#7C3AED" : "#0485F7";
            const fillColor = c.isVisual ? "#8B5CF6" : "#0485F7";
            return (
              <MilvusCollectionCard
                key={c.name}
                name={c.name}
                desc={c.desc}
                entities={c.entities}
                model={c.model}
                index={c.index}
                capacityPct={c.capacityPct}
                chipBg={chipBg}
                chipFg={chipFg}
                fillColor={fillColor}
                modelLabel={t("storage.model")}
                indexLabel={t("storage.indexKey")}
                entitiesCap={t("storage.entitiesCap")}
                capacityLabel={t("storage.capacityPct", { pct: Math.round(c.capacityPct) })}
              />
            );
          })}
        </div>
      </div>

      {/* Tabs */}
      <Panel>
        <div className="flex items-center gap-1 rounded-xl bg-background-secondary p-1">
          {tabs.map((tb) => {
            const active = tb.key === tab;
            return (
              <button
                key={tb.key}
                type="button"
                onClick={() => setTab(tb.key)}
                aria-pressed={active}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  active
                    ? "bg-surface text-foreground shadow-[0_1px_3px_0_rgba(0,0,0,0.08)]"
                    : "text-foreground-tertiary hover:text-foreground"
                }`}
              >
                {tb.label}
              </button>
            );
          })}
        </div>

        {tab === "documents" ? (
          <div className="-mx-5 -mb-5 mt-1 overflow-x-auto border-t border-border">
            <KBDocumentsTable
              documents={documents}
              total={docTotal}
              loading={docsQuery.isLoading}
              page={docPage}
              pageSize={docPageSize}
              onPageChange={setDocPage}
              onPageSizeChange={(size) => {
                setDocPageSize(size);
                setDocPage(1);
              }}
              onUpload={goToIngest}
              onDelete={setDocToDelete}
              onPreview={(doc) => {
                const target = {
                  kind: "file" as const,
                  documentId: doc.document_id,
                  title: doc.name,
                  sourceType: doc.source_type ?? null,
                  sourceUri: doc.source_uri ?? null,
                };
                prefetchPreviewResource(queryClient, target);
                openPreview(target, queryClient);
              }}
            />
          </div>
        ) : null}

        {tab === "logs" ? (
          <div className="-mx-5 -mb-5 mt-1 overflow-x-auto border-t border-border">
            <TaskTable
              tasks={tasks}
              loading={tasksQuery.isLoading}
              error={tasksQuery.error ? errorMessage(tasksQuery.error) : null}
              total={taskTotal}
              page={logPage}
              pageSize={logPageSize}
              onPageChange={setLogPage}
              onPageSizeChange={(size) => {
                setLogPageSize(size);
                setLogPage(1);
              }}
              hideKbBadge
              emptyHint={t("logsEmpty")}
              onRetryLoad={() => void tasksQuery.refetch()}
              onViewLogs={setLogsTask}
              onRetry={(task) => void retryTask.mutateAsync(task.job_id)}
              onDelete={(task) => void deleteTask.mutateAsync(task.job_id)}
            />
          </div>
        ) : null}

        {tab === "maintenance" ? (
          <div className="flex flex-col gap-5 pt-1">
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold text-foreground">{t("maintenance.title")}</h3>
              <p className="max-w-2xl text-sm leading-relaxed text-foreground-secondary">
                {t("maintenance.desc")}
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="h-full shadow-sm">
                <Card.Header className="flex flex-row items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100">
                    <AlertTriangle className="h-5 w-5 text-amber-600" aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-col gap-1">
                    <Card.Title className="text-[15px]">{t("maintenance.rebuild")}</Card.Title>
                    <Card.Description className="text-sm leading-relaxed">
                      {t("maintenance.rebuildDesc")}
                    </Card.Description>
                  </div>
                </Card.Header>
                <Card.Content>
                  <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3.5 py-3">
                    <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
                    <p className="text-xs leading-relaxed text-amber-800">
                      {t("maintenance.rebuildHint")}
                    </p>
                  </div>
                </Card.Content>
                <Card.Footer className="flex justify-end">
                  <Button variant="secondary" isDisabled={rebuild.isPending} onPress={runRebuild}>
                    <RefreshCw
                      className={`h-4 w-4 ${rebuild.isPending ? "animate-spin" : ""}`}
                      aria-hidden
                    />
                    {t("maintenance.rebuild")}
                  </Button>
                </Card.Footer>
              </Card>

              <Card className="h-full shadow-sm">
                <Card.Header className="flex flex-row items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-100">
                    <AlertOctagon className="h-5 w-5 text-red-600" aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-col gap-1">
                    <Card.Title className="text-[15px]">{t("maintenance.purge")}</Card.Title>
                    <Card.Description className="text-sm leading-relaxed">
                      {t("maintenance.purgeDesc")}
                    </Card.Description>
                  </div>
                </Card.Header>
                <Card.Content>
                  <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3.5 py-3">
                    <AlertTriangle
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600"
                      aria-hidden
                    />
                    <p className="text-xs leading-relaxed text-red-800">
                      {t("maintenance.purgeHint")}
                    </p>
                  </div>
                </Card.Content>
                <Card.Footer className="flex justify-end">
                  <Button variant="danger" isDisabled={deleteKB.isPending} onPress={runPurge}>
                    <Trash2 className="h-4 w-4" aria-hidden />
                    {t("maintenance.purge")}
                  </Button>
                </Card.Footer>
              </Card>
            </div>
          </div>
        ) : null}
      </Panel>

      <EditKBDrawer kb={kb} isOpen={editOpen} onOpenChange={setEditOpen} />
      <RebuildConfirmModal
        kb={kb}
        isOpen={rebuildOpen}
        onOpenChange={setRebuildOpen}
        onConfirm={confirmRebuild}
        isPending={rebuild.isPending}
      />
      <PurgeConfirmModal
        kb={kb}
        isOpen={purgeOpen}
        onOpenChange={setPurgeOpen}
        onConfirm={confirmPurge}
        isPending={deleteKB.isPending}
        error={purgeError}
      />
      <DocumentDeleteModal
        docName={docToDelete?.name ?? ""}
        docId={docToDelete?.document_id ?? ""}
        isOpen={docToDelete !== null}
        onOpenChange={(open) => {
          if (!open) setDocToDelete(null);
        }}
        onConfirm={confirmDeleteDoc}
        isPending={deleteDoc.isPending}
      />
      {logsTask ? (
        <TaskLogsModal
          task={logsTask}
          onClose={() => setLogsTask(null)}
          onRetry={(task) => void retryTask.mutateAsync(task.job_id)}
        />
      ) : null}
    </div>
  );
}
