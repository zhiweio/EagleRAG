import { HealthHeaderActions } from "@/components/health/HealthHeaderActions";
import { McpConfigCard } from "@/components/health/McpConfigCard";
import { ServiceGrid } from "@/components/health/ServiceGrid";
import { PageHeader } from "@/components/ui";
import { getTranslations, setRequestLocale } from "next-intl/server";

export default async function HealthPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations("health");

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-6">
        <PageHeader title={t("title")} subtitle={t("subtitle")} actions={<HealthHeaderActions />} />
        <ServiceGrid />
        <McpConfigCard />
      </main>
    </div>
  );
}
