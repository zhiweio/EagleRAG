"use client";

import { Link } from "@/i18n/routing";
import { useKnowledgeBases } from "@/lib/hooks/useKB";
import { useUserPreferences } from "@/lib/hooks/useUser";
import { formatRelative } from "@/lib/kb/types";
import { useKBStore } from "@/lib/stores/kbStore";
import { Drawer } from "@heroui/react";
import {
  Check,
  ChevronsUpDown,
  History,
  Layers,
  LayoutGrid,
  LibraryBig,
  Search,
  Settings2,
  X,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { KBBadge } from "./kb-visuals";

type Scope = "all" | "recent";

export function KBPicker() {
  const t = useTranslations("kb.picker");
  const locale = useLocale();
  const { kbName, setKbName } = useKBStore();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("all");

  const { data } = useKnowledgeBases({ sort: "name", limit: 200 });
  const { data: prefs } = useUserPreferences();
  const all = data?.items ?? [];

  useEffect(() => {
    if (kbName || !prefs?.default_kb_name) return;
    setKbName(String(prefs.default_kb_name));
  }, [kbName, prefs?.default_kb_name, setKbName]);
  const current = useMemo(() => all.find((k) => k.kbName === kbName), [all, kbName]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = scope === "recent" ? all.filter((k) => k.recent) : all;
    if (!q) return base;
    return base.filter(
      (k) => k.kbName.toLowerCase().includes(q) || k.displayName.toLowerCase().includes(q),
    );
  }, [all, query, scope]);

  const recent = useMemo(() => filtered.filter((k) => k.recent), [filtered]);
  const showGroups = scope === "all" && !query;

  const select = (name: string) => {
    setKbName(name);
    setOpen(false);
    setQuery("");
  };

  const renderRow = (k: (typeof all)[number]) => {
    const active = k.kbName === kbName;
    const collection = k.collections[0] ?? "eagle_text";
    const meta = [
      t("docsShort", { count: k.documents.toLocaleString() }),
      collection,
      formatRelative(k.updatedAgoMs, locale),
    ].join(" · ");
    return (
      <button
        key={k.kbName}
        type="button"
        onClick={() => select(k.kbName)}
        aria-pressed={active}
        className={`relative flex h-[54px] w-full items-center gap-[11px] rounded-lg py-2 pl-3 pr-2.5 text-left transition-colors ${
          active ? "bg-accent-soft" : "hover:bg-(--surface-muted)"
        }`}
      >
        {active ? (
          <span
            className="absolute left-0 top-1/2 h-[26px] w-[3px] -translate-y-1/2 rounded-full bg-accent"
            aria-hidden
          />
        ) : null}
        <KBBadge theme={k.theme} icon={k.icon} size={36} iconSize={18} radius={8} />
        <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
          <span className="flex items-center gap-[7px]">
            <span className="truncate font-mono text-[13px] font-semibold text-foreground">
              {k.kbName}
            </span>
            <span className="shrink-0 rounded-sm bg-(--surface-muted) px-1.5 py-0.5 text-[10.5px] font-medium text-foreground-secondary">
              {k.displayName}
            </span>
          </span>
          <span className="truncate text-[11px] text-foreground-tertiary">{meta}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2.5">
          <span className="rounded-full bg-(--surface-muted) px-2 py-0.5 text-[11px] font-medium text-foreground-tertiary">
            {t("nodes", { count: k.graphNodes })}
          </span>
          <span className="flex h-[18px] w-[18px] items-center justify-center">
            {active ? <Check className="h-[18px] w-[18px] text-accent" aria-hidden /> : null}
          </span>
        </span>
      </button>
    );
  };

  const scopes: { key: Scope; label: string; icon: typeof LibraryBig }[] = [
    { key: "all", label: t("scope.all"), icon: LibraryBig },
    { key: "recent", label: t("scope.recent"), icon: History },
  ];

  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="flex h-9 cursor-pointer items-center gap-2 rounded-xl border border-border bg-surface pl-2 pr-2.5 text-left transition-colors hover:bg-(--surface-muted)"
      >
        {current ? (
          <KBBadge theme={current.theme} icon={current.icon} size={24} iconSize={13} radius={6} />
        ) : (
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-(--surface-muted) text-foreground-secondary">
            <LayoutGrid className="h-3.5 w-3.5" aria-hidden />
          </span>
        )}
        <span className="hidden max-w-[140px] flex-col leading-tight sm:flex">
          <span className="truncate text-xs font-semibold text-foreground">
            {current ? current.displayName : t("default")}
          </span>
          <span className="truncate font-mono text-[10px] text-foreground-tertiary">
            {current ? current.kbName : "all"}
          </span>
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-foreground-tertiary" aria-hidden />
      </button>
      <Drawer isOpen={open} onOpenChange={setOpen}>
        <Drawer.Backdrop className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
          <Drawer.Content
            placement="right"
            className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
          >
            <Drawer.Dialog className="w-full !max-w-none sm:w-1/3 sm:!max-w-[640px] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
              <Drawer.Header className="flex flex-col gap-3 border-b border-separator px-3.5 pb-3 pt-3.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-[30px] w-[30px] items-center justify-center rounded-lg bg-accent-soft">
                      <LibraryBig
                        className="h-[17px] w-[17px] text-accent-soft-foreground"
                        aria-hidden
                      />
                    </span>
                    <div className="flex flex-col gap-px">
                      <Drawer.Heading className="text-sm font-semibold text-foreground">
                        {t("title")}
                      </Drawer.Heading>
                      <span className="font-mono text-[10px] text-foreground-tertiary">
                        {t("single")}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 rounded-full bg-(--surface-muted) px-2.5 py-1 text-[11px] font-semibold text-foreground-secondary">
                      <Layers className="h-3 w-3" aria-hidden />
                      {t("count", { count: all.length })}
                    </span>
                    <Drawer.CloseTrigger
                      aria-label={t("hint.close")}
                      className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-(--surface-muted) text-foreground-secondary transition-colors hover:bg-(--separator)"
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                    </Drawer.CloseTrigger>
                  </div>
                </div>

                {/* Search */}
                <div className="flex h-10 items-center gap-2.5 rounded-xl border border-border bg-surface px-3 focus-within:border-field-border-focus">
                  <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t("searchPlaceholder")}
                    className="w-full min-w-0 bg-transparent text-[13px] text-foreground outline-none placeholder:text-foreground-secondary"
                  />
                  <kbd className="rounded-sm border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] font-semibold text-foreground-tertiary">
                    esc
                  </kbd>
                </div>

                {/* Scope segmented control */}
                <div className="flex h-[34px] items-center gap-0.5 rounded-lg bg-(--surface-muted) p-0.5">
                  {scopes.map((s) => {
                    const activeScope = scope === s.key;
                    const Icon = s.icon;
                    return (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => setScope(s.key)}
                        aria-pressed={activeScope}
                        className={`flex h-full flex-1 items-center justify-center gap-1.5 rounded-md text-xs font-semibold transition-colors ${
                          activeScope
                            ? "bg-surface text-foreground shadow-[0_1px_3px_0_rgba(0,0,0,0.08)]"
                            : "text-foreground-secondary hover:text-foreground"
                        }`}
                      >
                        <Icon className="h-[13px] w-[13px]" aria-hidden />
                        {s.label}
                      </button>
                    );
                  })}
                </div>
              </Drawer.Header>

              {/* Body */}
              <Drawer.Body className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
                {filtered.length === 0 ? (
                  <p className="px-2 py-8 text-center text-sm text-foreground-tertiary">
                    {t("empty")}
                  </p>
                ) : showGroups ? (
                  <>
                    {recent.length > 0 ? (
                      <>
                        <p className="px-3 pb-1 pt-1.5 text-[11px] font-semibold tracking-[0.3px] text-foreground-tertiary">
                          {t("recent")}
                        </p>
                        {recent.map(renderRow)}
                        <div className="my-1 h-px bg-(--separator)" />
                      </>
                    ) : null}
                    <p className="px-3 pb-1 pt-1.5 text-[11px] font-semibold tracking-[0.3px] text-foreground-tertiary">
                      {t("all", { count: filtered.length })}
                    </p>
                    {filtered.map(renderRow)}
                  </>
                ) : (
                  filtered.map(renderRow)
                )}
              </Drawer.Body>

              {/* Footer */}
              <Drawer.Footer className="flex items-center justify-between border-t border-separator px-3.5 py-2.5">
                <div className="flex items-center gap-3.5">
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground-tertiary">
                    <kbd className="rounded-sm border border-border bg-surface px-1.5 py-px font-mono text-[11px] font-semibold text-foreground-secondary">
                      ↑↓
                    </kbd>
                    {t("hint.nav")}
                  </span>
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground-tertiary">
                    <kbd className="rounded-sm border border-border bg-surface px-1.5 py-px font-mono text-[11px] font-semibold text-foreground-secondary">
                      ↵
                    </kbd>
                    {t("hint.select")}
                  </span>
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground-tertiary">
                    <kbd className="rounded-sm border border-border bg-surface px-1.5 py-px font-mono text-[11px] font-semibold text-foreground-secondary">
                      esc
                    </kbd>
                    {t("hint.close")}
                  </span>
                </div>
                <Link
                  href="/kb"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-1.5 text-xs font-semibold text-accent-soft-foreground hover:underline"
                >
                  <Settings2 className="h-[13px] w-[13px]" aria-hidden />
                  {t("manage")}
                </Link>
              </Drawer.Footer>
            </Drawer.Dialog>
          </Drawer.Content>
        </Drawer.Backdrop>
      </Drawer>
    </>
  );
}
