import { KBManagementClient } from "@/components/kb/KBManagementClient";
import { setRequestLocale } from "next-intl/server";

export default async function KnowledgeBasePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-6">
        <KBManagementClient />
      </main>
    </div>
  );
}
