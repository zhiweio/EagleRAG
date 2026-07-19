"use client";

import { cn } from "@/components/ui";
import { Image, ScanSearch, ScanText } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

export type RoutingMode = "auto" | "knowhere" | "pixelrag";

const MODES: { key: RoutingMode; icon: LucideIcon }[] = [
  { key: "auto", icon: ScanSearch },
  { key: "knowhere", icon: ScanText },
  { key: "pixelrag", icon: Image },
];

/**
 * RoutingModeCards — routing-strategy radio card group (Auto / force Knowhere / force PixelRAG).
 * Selected card: accent border + accent-soft fill + solid radio dot.
 */
export function RoutingModeCards({
  value,
  onChange,
}: {
  value: RoutingMode;
  onChange: (mode: RoutingMode) => void;
}) {
  const t = useTranslations("ingest.routing");
  return (
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
      {MODES.map(({ key, icon: Icon }) => {
        const selected = value === key;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(key)}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-3 text-left transition-colors",
              selected
                ? "border-accent bg-accent-soft"
                : "border-border bg-surface hover:border-accent/40",
            )}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden
                className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2",
                  selected ? "border-accent" : "border-foreground-tertiary",
                )}
              >
                {selected && <span className="h-2 w-2 rounded-full bg-accent" />}
              </span>
              <Icon
                size={15}
                strokeWidth={2}
                aria-hidden
                className={selected ? "text-accent" : "text-foreground-secondary"}
              />
              <span className="text-[13px] font-semibold text-foreground">{t(`${key}.title`)}</span>
            </span>
            <span className="pl-6 text-[11px] leading-relaxed text-foreground-secondary">
              {t(`${key}.desc`)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
