"use client";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Link } from "@/i18n/routing";
import { useUIStore } from "@/lib/stores/uiStore";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useEffect, useState } from "react";

function SearchKbd() {
  const [mod, setMod] = useState("⌘");
  useEffect(() => {
    const isMac =
      typeof navigator !== "undefined" &&
      /Mac|iPhone|iPad|iPod/.test(navigator.platform ?? navigator.userAgent);
    setMod(isMac ? "⌘" : "Ctrl");
  }, []);
  return (
    <span className="hidden shrink-0 items-center gap-0.5 sm:flex">
      <kbd className="flex h-[18px] items-center rounded border border-border bg-background px-1.5 font-mono text-[10px] font-semibold text-foreground-tertiary">
        {mod}
      </kbd>
      <kbd className="flex h-[18px] items-center rounded border border-border bg-background px-1.5 font-mono text-[10px] font-semibold text-foreground-tertiary">
        K
      </kbd>
    </span>
  );
}

/**
 * AppBar — global top bar. Primary navigation lives in the left Sidebar; this bar
 * carries the global document search on the left and the locale switcher on the
 * right. Below lg the sidebar is hidden, so the brand reappears on the left.
 */
export function AppBar() {
  const t = useTranslations();
  const setGlobalSearchOpen = useUIStore((s) => s.setGlobalSearchOpen);

  return (
    <header className="sticky top-0 z-30 h-16 border-b border-border bg-surface/90 backdrop-blur">
      <div className="flex h-16 w-full items-center gap-3 px-4 sm:px-6">
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
          <span className="hidden flex-col leading-tight sm:flex">
            <span className="text-[15px] font-semibold tracking-tight text-foreground">
              {t("app.name")}
            </span>
            <span className="text-[11px] font-medium text-foreground-tertiary">
              {t("app.tagline")}
            </span>
          </span>
        </Link>

        {/* Global document search trigger */}
        <button
          type="button"
          onClick={() => setGlobalSearchOpen(true)}
          aria-label={t("globalSearch.shortcut")}
          className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-background px-3 text-left shadow-[0_1px_3px_0_rgba(0,0,0,0.04)] transition-colors hover:border-accent/40 hover:bg-accent-soft/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent lg:max-w-md lg:flex-none"
        >
          <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
          <span className="min-w-0 flex-1 truncate text-sm text-foreground-secondary">
            {t("globalSearch.placeholder")}
          </span>
          <SearchKbd />
        </button>

        {/* Right · deployment domain (read-only) + locale */}
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <span
            className="hidden rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-foreground-secondary sm:inline"
            title={t("app.domainHint")}
          >
            {t("app.domain", {
              domain: process.env.NEXT_PUBLIC_PLUGIN_NAMESPACE ?? "core",
            })}
          </span>
          <LocaleSwitcher />
        </div>
      </div>
    </header>
  );
}
