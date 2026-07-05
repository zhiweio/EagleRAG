import { KBDetailClient } from "@/components/kb/KBDetailClient";
import { setRequestLocale } from "next-intl/server";

export default async function KnowledgeBaseDetailPage({
  params,
}: {
  params: Promise<{ locale: string; kbName: string }>;
}) {
  const { locale, kbName } = await params;
  setRequestLocale(locale);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-6">
        <KBDetailClient kbName={decodeURIComponent(kbName)} />
      </main>
    </div>
  );
}
