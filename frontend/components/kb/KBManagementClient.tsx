"use client";

import { type KBSort, useKBOverview, useKnowledgeBases } from "@/lib/hooks/useKB";
import { ArrowUpDown, Database, FileStack, LibraryBig, Plus, Search, Share2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { CreateKBDrawer } from "./CreateKBDrawer";
import { KBCard } from "./KBCard";
import { KBGhostCard } from "./KBGhostCard";
import { KBStatCard, type KBStatDef } from "./KBStatCard";
import { KBToastProvider } from "./KBToast";

export function KBManagementClient() {
  const t = useTranslations("kb.management");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<KBSort>("recent");
  const [createOpen, setCreateOpen] = useState(false);

  const { data: overviewData } = useKBOverview();
  const { data: listData, isLoading } = useKnowledgeBases({ query, sort });

  const overview = overviewData ?? {
    kbCount: 0,
    activeIngestions: 0,
    totalDocuments: 0,
    totalGraphNodes: 0,
    totalVectors: 0,
  };
  const items = listData?.items ?? [];

  const stats: KBStatDef[] = [
    {
      icon: LibraryBig,
      color: "#0485F7",
      soft: "#0485F726",
      cap: t("stats.kbCount"),
      value: overview.kbCount.toLocaleString(),
      sub: t("stats.kbCountSub", { count: overview.activeIngestions }),
    },
    {
      icon: FileStack,
      color: "#2563EB",
      soft: "#DBEAFE",
      cap: t("stats.docs"),
      value: overview.totalDocuments.toLocaleString(),
      sub: t("stats.docsSub"),
    },
    {
      icon: Share2,
      color: "#059669",
      soft: "#D1FAE5",
      cap: t("stats.nodes"),
      value: overview.totalGraphNodes.toLocaleString(),
      sub: t("stats.nodesSub"),
    },
    {
      icon: Database,
      color: "#7C3AED",
      soft: "#EDE9FE",
      cap: t("stats.vectors"),
      value: overview.totalVectors.toLocaleString(),
      sub: t("stats.vectorsSub"),
    },
  ];

  return (
    <KBToastProvider>
      <div className="flex flex-col gap-6">
        {/* Page header — title pinned top-left, controls on their own right-aligned row */}
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <h1 className="flex items-center gap-2 text-2xl font-semibold text-foreground">
              <LibraryBig className="h-6 w-6 shrink-0 text-accent" aria-hidden />
              {t("title")}
            </h1>
            <p className="text-sm text-foreground-secondary">{t("subtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2.5">
            <div className="flex h-[42px] items-center gap-2 rounded-xl border border-border bg-surface px-3 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)] focus-within:border-field-border-focus">
              <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("searchPlaceholder")}
                className="w-full min-w-0 bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-secondary sm:w-56"
              />
            </div>
            <div className="relative flex h-[42px] items-center gap-2 rounded-xl border border-border bg-surface px-3.5 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)]">
              <ArrowUpDown className="h-[15px] w-[15px] text-foreground-secondary" aria-hidden />
              <select
                aria-label={t("sort")}
                value={sort}
                onChange={(e) => setSort(e.target.value as KBSort)}
                className="cursor-pointer appearance-none bg-transparent pr-1 text-sm font-medium text-foreground outline-none"
              >
                <option value="recent">{t("sortRecent")}</option>
                <option value="name">{t("sortName")}</option>
                <option value="size">{t("sortSize")}</option>
              </select>
            </div>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="flex h-[42px] items-center gap-2 rounded-xl bg-accent px-[18px] text-sm font-semibold text-accent-foreground shadow-[0_5px_14px_0_rgba(4,133,247,0.25)] transition-colors hover:bg-accent-hover"
            >
              <Plus className="h-[17px] w-[17px]" aria-hidden />
              {t("create")}
            </button>
          </div>
        </div>

        {/* Overview stats */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((def) => (
            <KBStatCard key={def.cap} def={def} />
          ))}
        </div>

        {/* Card grid */}
        {isLoading ? (
          <p className="py-12 text-center text-sm text-foreground-tertiary">…</p>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border py-16 text-center text-sm text-foreground-tertiary">
            {t("empty")}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((kb) => (
              <KBCard key={kb.kbName} kb={kb} />
            ))}
            <KBGhostCard
              title={t("ghost.title")}
              sub={t("ghost.sub")}
              onClick={() => setCreateOpen(true)}
            />
          </div>
        )}
      </div>

      <CreateKBDrawer isOpen={createOpen} onOpenChange={setCreateOpen} />
    </KBToastProvider>
  );
}
