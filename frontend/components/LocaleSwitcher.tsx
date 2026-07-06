"use client";

import { usePathname, useRouter } from "@/i18n/routing";
import { Button, Popover } from "@heroui/react";
import { Check, ChevronDown, Globe } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState, useTransition } from "react";

const LOCALES = [
  { value: "zh", short: "简" },
  { value: "en", short: "EN" },
] as const;

type LocaleValue = (typeof LOCALES)[number]["value"];

/**
 * LocaleSwitcher — bordered pill trigger with a HeroUI Popover menu.
 * Design ref (frame 02 · Locale Switcher): h36, r-full, border, gap6, px10.
 */
export function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations("locale");
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  const current = LOCALES.find((item) => item.value === locale) ?? LOCALES[0];
  const alternate = LOCALES.find((item) => item.value !== locale) ?? LOCALES[1];

  function onSelect(nextLocale: LocaleValue) {
    if (nextLocale === locale) {
      setOpen(false);
      return;
    }
    setOpen(false);
    startTransition(() => {
      router.replace(pathname, { locale: nextLocale });
    });
  }

  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Button
        aria-label={t("switch")}
        aria-expanded={open}
        isDisabled={isPending}
        variant="tertiary"
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 text-foreground hover:bg-background-secondary"
      >
        <Globe size={16} strokeWidth={2} className="text-foreground-secondary" aria-hidden />
        <span className="text-[13px] font-medium">
          {current.short} / {alternate.short}
        </span>
        <ChevronDown
          size={14}
          strokeWidth={2}
          className={`text-foreground-tertiary transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </Button>
      <Popover.Content className="min-w-44 p-0" placement="bottom end">
        <Popover.Dialog aria-label={t("switch")}>
          <div className="flex flex-col gap-0.5 p-1.5">
            {LOCALES.map((item) => {
              const selected = item.value === locale;
              return (
                <button
                  key={item.value}
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  disabled={isPending}
                  onClick={() => onSelect(item.value)}
                  className={`flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                    selected
                      ? "bg-accent-soft text-accent"
                      : "text-foreground hover:bg-(--surface-muted)"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="w-5 shrink-0 font-mono text-[11px] font-semibold text-foreground-tertiary">
                      {item.short}
                    </span>
                    <span className="font-medium">{t(item.value)}</span>
                  </span>
                  {selected ? (
                    <Check className="h-4 w-4 shrink-0" strokeWidth={2.5} aria-hidden />
                  ) : null}
                </button>
              );
            })}
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}
