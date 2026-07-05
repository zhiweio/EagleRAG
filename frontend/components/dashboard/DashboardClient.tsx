"use client";

import { DashboardHealthCard } from "@/components/dashboard/DashboardHealthCard";
import { DashboardIngestCard } from "@/components/dashboard/DashboardIngestCard";
import { DashboardKBCard } from "@/components/dashboard/DashboardKBCard";
import { DashboardQACard } from "@/components/dashboard/DashboardQACard";
import { PageHeader } from "@/components/ui";
import { useTranslations } from "next-intl";

/**
 * DashboardClient — hero headline plus four module cards (light theme / HeroUI v3).
 */
export function DashboardClient() {
  const t = useTranslations("dashboard");

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 sm:py-8">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

      <section
        aria-label={t("modulesLabel")}
        className="grid grid-cols-1 gap-5 lg:grid-cols-3 lg:items-stretch"
      >
        <div className="min-h-0 lg:col-span-2">
          <DashboardQACard />
        </div>
        <div className="min-h-0 lg:col-span-1">
          <DashboardIngestCard />
        </div>
        <div className="min-h-0 lg:col-span-2">
          <DashboardKBCard />
        </div>
        <div className="min-h-0 lg:col-span-1">
          <DashboardHealthCard />
        </div>
      </section>
    </main>
  );
}
