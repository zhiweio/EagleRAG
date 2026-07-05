"use client";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Link } from "@/i18n/routing";
import { useTranslations } from "next-intl";
import Image from "next/image";

/**
 * AppBar — global top bar. Primary navigation and the account/settings controls
 * live in the left Sidebar; this bar only carries the locale switcher on the
 * right. Below lg the sidebar is hidden, so the brand reappears on the left.
 */
export function AppBar() {
  const t = useTranslations();

  return (
    <header className="sticky top-0 z-30 h-16 border-b border-border bg-surface/90 backdrop-blur">
      <div className="flex h-16 w-full items-center justify-between px-6">
        {/* Left · brand (mobile only; sidebar owns it on lg+) */}
        <Link href="/" className="flex shrink-0 items-center gap-3 lg:hidden">
          <Image
            src="/logo.png"
            alt=""
            width={32}
            height={32}
            aria-hidden
            className="h-8 w-8 shrink-0 rounded-full"
          />
          <span className="flex flex-col leading-tight">
            <span className="text-[15px] font-semibold tracking-tight text-foreground">
              {t("app.name")}
            </span>
            <span className="text-[11px] font-medium text-foreground-tertiary">
              {t("app.tagline")}
            </span>
          </span>
        </Link>

        {/* Right · locale */}
        <div className="ml-auto flex items-center">
          <LocaleSwitcher />
        </div>
      </div>
    </header>
  );
}
