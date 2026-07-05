"use client";

import { cn } from "@/components/ui";
import { Link, usePathname } from "@/i18n/routing";
import { useUser } from "@/lib/hooks/useUser";
import { usePrefsStore } from "@/lib/stores/prefsStore";
import {
  Activity,
  CloudUpload,
  LibraryBig,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useEffect, useState } from "react";

/**
 * Sidebar — global left navigation rail (visible on lg+). Houses the brand at
 * the top, the four primary destinations (Q&A / Ingestion / Knowledge Bases /
 * Service Health) as an icon + label list, and — anchored to the bottom like a
 * mature SaaS shell — a collapse toggle, the account row, and settings.
 *
 * The rail collapses to an icon-only rail; the state is persisted per-browser in
 * `usePrefsStore`. A mount guard keeps the first client render matching the
 * server (always expanded) to avoid a hydration mismatch, then applies the
 * stored preference.
 */
const ENTRIES: { href: "/health" | "/qa" | "/ingest" | "/kb"; key: string; icon: LucideIcon }[] = [
  { href: "/qa", key: "nav.qa", icon: MessagesSquare },
  { href: "/ingest", key: "nav.ingest", icon: CloudUpload },
  { href: "/kb", key: "nav.kb", icon: LibraryBig },
  { href: "/health", key: "nav.health", icon: Activity },
];

export function Sidebar() {
  const t = useTranslations();
  const pathname = usePathname();
  const { data: user } = useUser();

  const storedCollapsed = usePrefsStore((s) => s.sidebarCollapsed);
  const toggleSidebar = usePrefsStore((s) => s.toggleSidebar);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const collapsed = mounted && storedCollapsed;

  function isActive(href: string): boolean {
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <>
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 ease-out motion-reduce:transition-none lg:flex",
          collapsed ? "w-16" : "w-60",
        )}
      >
        {/* Brand + collapse toggle (top) */}
        {collapsed ? (
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label={t("app.expandSidebar")}
            title={t("app.expandSidebar")}
            className="group relative flex h-16 shrink-0 items-center justify-center"
          >
            {/* Brand mark; fades out to reveal the expand affordance on hover/focus */}
            <Image
              src="/logo.png"
              alt=""
              width={32}
              height={32}
              aria-hidden
              className="h-8 w-8 shrink-0 rounded-full transition-opacity duration-150 group-hover:opacity-0 group-focus-visible:opacity-0 motion-reduce:transition-none"
            />
            <PanelLeftOpen
              size={18}
              strokeWidth={2}
              aria-hidden
              className="absolute text-foreground-secondary opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
            />
          </button>
        ) : (
          <div className="flex h-16 shrink-0 items-center justify-between py-0 pr-3 pl-5">
            <Link href="/" aria-label={t("app.name")} className="flex items-center gap-3">
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
            <button
              type="button"
              onClick={toggleSidebar}
              aria-label={t("app.collapseSidebar")}
              title={t("app.collapseSidebar")}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-foreground-tertiary transition-colors hover:bg-background-secondary hover:text-foreground"
            >
              <PanelLeftClose size={18} strokeWidth={2} aria-hidden />
            </button>
          </div>
        )}

        {/* Primary nav */}
        <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
          {ENTRIES.map((entry) => {
            const active = isActive(entry.href);
            const Icon = entry.icon;
            const label = t(entry.key);
            return (
              <Link
                key={entry.href}
                href={entry.href}
                aria-current={active ? "page" : undefined}
                aria-label={collapsed ? label : undefined}
                title={collapsed ? label : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-xl py-2.5 text-sm transition-colors",
                  collapsed ? "justify-center px-0" : "px-3",
                  active
                    ? "bg-accent-soft font-medium text-accent-soft-foreground"
                    : "text-foreground-secondary hover:bg-background-secondary hover:text-foreground",
                )}
              >
                <Icon
                  size={18}
                  strokeWidth={2}
                  aria-hidden
                  className={cn("shrink-0", active ? "text-accent" : "text-foreground-tertiary")}
                />
                {!collapsed && <span className="truncate">{label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Account · settings (bottom, SaaS-shell style) — placeholder, no-op until wired up */}
        <div
          className={cn(
            "mt-2 flex border-t border-border p-3",
            collapsed ? "flex-col items-center gap-2" : "items-center gap-1.5",
          )}
        >
          <button
            type="button"
            aria-label={user?.display_name ?? t("app.profile")}
            title={collapsed ? (user?.display_name ?? t("app.profile")) : undefined}
            className={cn(
              "flex items-center rounded-xl",
              collapsed ? "justify-center p-1" : "min-w-0 flex-1 gap-2.5 px-2 py-1.5 text-left",
            )}
          >
            <span
              aria-hidden
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-(--bubble) text-xs font-medium text-foreground"
            >
              {user?.avatar_initials ?? "ZQ"}
            </span>
            {!collapsed && (
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="truncate text-[13px] font-medium text-foreground">
                  {user?.display_name ?? t("app.profile")}
                </span>
                <span className="truncate text-[11px] text-foreground-tertiary">
                  {t("app.manageAccount")}
                </span>
              </span>
            )}
          </button>
          <button
            type="button"
            aria-label={t("app.settings")}
            title={t("app.settings")}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-foreground-secondary"
          >
            <Settings size={18} strokeWidth={2} aria-hidden />
          </button>
        </div>
      </aside>
    </>
  );
}
