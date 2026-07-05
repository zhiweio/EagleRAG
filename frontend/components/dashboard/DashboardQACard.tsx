"use client";

import { DashboardSurfaceCard } from "@/components/dashboard/DashboardSurfaceCard";
import { FileBadge } from "@/components/kb/kb-visuals";
import { Chip } from "@/components/ui";
import { Link, useRouter } from "@/i18n/routing";
import { useDocuments } from "@/lib/hooks/useDocuments";
import { ArrowRight, MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

/**
 * DashboardQACard — multimodal Q&A entry (design ref: try-it-out chips + composer).
 */
export function DashboardQACard() {
  const t = useTranslations("dashboard.qaCard");
  const router = useRouter();
  const [query, setQuery] = useState("");
  const { data } = useDocuments({ limit: 2, status: "ready" });
  const samples = data?.items ?? [];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/qa?q=${encodeURIComponent(q)}` : "/qa");
  }

  return (
    <DashboardSurfaceCard title={t("title")} icon={MessagesSquare} iconVariant="accent-soft">
      <p className="text-sm leading-relaxed text-foreground-secondary">{t("description")}</p>

      <div className="flex flex-col gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-foreground-tertiary uppercase">
          {t("tryItOut")}
        </span>
        <div className="flex flex-wrap gap-2">
          {samples.length === 0 ? (
            <Chip tone="neutral" size="sm">
              {t("noSamples")}
            </Chip>
          ) : (
            samples.map((doc) => (
              <Link
                key={doc.document_id}
                href="/qa"
                className="inline-flex items-center gap-2 rounded-full border border-border bg-(--surface-muted) px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent/40 hover:bg-accent-soft"
              >
                <FileBadge name={doc.name} size={14} />
                <span className="max-w-[10rem] truncate">{doc.name}</span>
              </Link>
            ))
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="mt-auto">
        <div className="flex items-center gap-2 rounded-xl border border-border bg-field-background px-3 py-2 shadow-[var(--field-shadow)] focus-within:border-field-border-focus">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("placeholder")}
            className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-field-placeholder"
            aria-label={t("placeholder")}
          />
          <button
            type="submit"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground transition-colors hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            aria-label={t("submit")}
          >
            <ArrowRight className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </form>
    </DashboardSurfaceCard>
  );
}
