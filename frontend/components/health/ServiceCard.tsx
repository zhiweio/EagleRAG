"use client";

import { cn } from "@/components/ui";
import type { ServiceCardData } from "@/lib/health/types";
import { useTranslations } from "next-intl";
import { CHIP_TONE, ICON_TONE, STATUS_DOT } from "./health-visuals";

/**
 * ServiceCard — a single tile in the main service grid (design frame 03).
 * Layout: soft icon box + name (top-left) and a status pill (top-right), a
 * description line, up to two metric chips, and a footer with the uptime dot
 * and the last-checked timestamp.
 */
export function ServiceCard({
  data,
  onOpen,
}: {
  data: ServiceCardData;
  onOpen?: () => void;
}) {
  const t = useTranslations("health");
  const Icon = data.icon;
  const tone = ICON_TONE[data.tone];
  const interactive = Boolean(onOpen);
  const cardNs = data.i18nVariant
    ? (`serviceCards.${data.i18nKey}.${data.i18nVariant}` as const)
    : (`serviceCards.${data.i18nKey}` as const);

  return (
    <article
      className={cn(
        "flex flex-col gap-3.5 rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)] transition-shadow",
        interactive && "cursor-pointer hover:shadow-[0_4px_16px_0_rgba(0,0,0,0.08)]",
      )}
      onClick={onOpen}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen?.();
              }
            }
          : undefined
      }
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
    >
      {/* Header: icon + name / status pill */}
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className={cn(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
              tone.className,
            )}
            style={tone.style}
          >
            <Icon size={20} strokeWidth={2} />
          </span>
          <h3 className="truncate text-[15px] font-semibold text-foreground">
            {t(`${cardNs}.name`)}
          </h3>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-(--surface-muted) px-2.5 py-1 text-xs font-medium text-foreground-secondary">
          <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[data.status])} />
          {t(`status.${data.status}`)}
        </span>
      </header>

      {/* Description */}
      <p className="line-clamp-2 min-h-[2.5rem] text-[13px] leading-relaxed text-foreground-secondary">
        {t(`${cardNs}.desc`)}
      </p>

      {/* Metric chips */}
      <div className="flex flex-wrap items-center gap-2">
        {data.chips.map((chip) => (
          <span
            key={chip.label}
            className={cn(
              "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
              CHIP_TONE[chip.tone],
            )}
          >
            {chip.label}
          </span>
        ))}
      </div>

      {/* Footer: uptime + checked — mt-auto pins it to the card bottom so cards
          of differing content heights (1-line vs 2-line chips) stay aligned. */}
      <footer className="mt-auto flex items-center justify-between border-t border-border/70 pt-3 text-xs">
        <span className="inline-flex items-center gap-1.5 text-foreground-secondary">
          <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[data.status])} />
          {t("uptime", { value: data.uptime })}
        </span>
        <span className="text-foreground-tertiary">{t("checkedAgo")}</span>
      </footer>
    </article>
  );
}
