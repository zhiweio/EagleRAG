import { AppBar } from "@/components/AppBar";
import { IconBox } from "@/components/ui";
import { Link } from "@/i18n/routing";
import { Activity, LibraryBig, MessagesSquare, Upload } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations();

  const cards = [
    {
      href: "/qa" as const,
      title: t("nav.qa"),
      desc: t("home.qaDesc"),
      icon: MessagesSquare,
    },
    {
      href: "/ingest" as const,
      title: t("nav.ingest"),
      desc: t("home.ingestDesc"),
      icon: Upload,
    },
    {
      href: "/health" as const,
      title: t("nav.health"),
      desc: t("home.healthDesc"),
      icon: Activity,
    },
    {
      href: "/kb" as const,
      title: t("nav.kb"),
      desc: t("home.kbDesc"),
      icon: LibraryBig,
    },
  ];

  return (
    <div className="min-h-screen bg-background">
      <AppBar />
      <main className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-12">
        <section className="flex flex-col gap-3">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            {t("home.title")}
          </h1>
          <p className="max-w-2xl text-base text-foreground-secondary">{t("home.subtitle")}</p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {cards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)] transition-colors hover:border-accent hover:bg-accent-soft"
            >
              <IconBox icon={card.icon} variant="accent-soft" size={40} iconSize={20} radius="xl" />
              <span className="text-base font-semibold text-foreground">{card.title}</span>
              <span className="text-sm text-foreground-secondary">{card.desc}</span>
            </Link>
          ))}
        </section>
      </main>
    </div>
  );
}
