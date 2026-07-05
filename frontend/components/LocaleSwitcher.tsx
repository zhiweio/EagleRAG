"use client";

import { usePathname, useRouter } from "@/i18n/routing";
import { ChevronDown, Globe } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";

/**
 * LocaleSwitcher — bordered pill (globe + "ZH / EN" + chevron). A visually
 * hidden native <select> sits on top for keyboard/screen-reader access.
 * Design ref (frame 02 · Locale Switcher): h36, r-full, border, gap6, px10.
 */
export function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations("locale");
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  function onChange(nextLocale: string) {
    startTransition(() => {
      router.replace(pathname, { locale: nextLocale });
    });
  }

  return (
    <span className="relative inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 text-foreground transition-colors hover:bg-background-secondary focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-1">
      <Globe size={16} strokeWidth={2} className="text-foreground-secondary" aria-hidden />
      <span className="text-[13px] font-medium">
        {locale === "zh" ? "简" : "EN"} / {locale === "zh" ? "EN" : "简"}
      </span>
      <ChevronDown size={14} strokeWidth={2} className="text-foreground-tertiary" aria-hidden />
      <select
        className="absolute inset-0 cursor-pointer opacity-0"
        value={locale}
        aria-label={t("switch")}
        disabled={isPending}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="zh">中文</option>
        <option value="en">English</option>
      </select>
    </span>
  );
}
