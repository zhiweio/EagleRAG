"use client";

import { KBBadge } from "@/components/kb/kb-visuals";
import { Link } from "@/i18n/routing";
import { type KnowledgeBase, formatRelative } from "@/lib/kb/types";
import { Drawer } from "@heroui/react";
import {
  Archive,
  Check,
  ChevronsUpDown,
  Clock,
  History,
  Layers,
  LayoutGrid,
  Library,
  LibraryBig,
  Search,
  Settings2,
  Star,
  X,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Fragment, type ReactNode, useMemo, useState } from "react";

interface TargetKBSelectorProps {
  items: KnowledgeBase[];
  value: string;
  onChange: (kbName: string) => void;
}

type PickerScope = "all" | "recent" | "starred" | "archived";

const SCOPES: { key: PickerScope; icon: typeof Library }[] = [
  { key: "all", icon: Library },
  { key: "recent", icon: History },
  { key: "starred", icon: Star },
  { key: "archived", icon: Archive },
];

/** A single key in the command-palette footer. */
function Kbd({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-[18px] items-center rounded border border-border bg-surface px-1.5 font-mono text-[11px] font-semibold text-foreground-secondary">
      {children}
    </span>
  );
}

/** Footer hint: a key combo + descriptive label. */
function Hint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="flex items-center gap-[3px]">
        {keys.map((k) => (
          <Kbd key={k}>{k}</Kbd>
        ))}
      </span>
      <span className="text-[11px] font-medium text-foreground-tertiary">{label}</span>
    </span>
  );
}

/**
 * TargetKBSelector — "target knowledge base" picker inside the ingest upload card.
 * The trigger card shows the current KB (badge + name + current chip +
 * doc/collection/updated time); clicking it slides out a Drawer from the right
 * (search + scope segmented + recent/all grouping, single-select writes kb_name),
 * 1/3 screen width, full-width on mobile, capped at 640px; below sits a "recent"
 * quick chips row.
 */
export function TargetKBSelector({ items, value, onChange }: TargetKBSelectorProps) {
  const t = useTranslations("ingest.upload");
  const tp = useTranslations("kb.picker");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<PickerScope>("all");

  const current = useMemo(() => items.find((k) => k.kbName === value), [items, value]);
  const recent = useMemo(() => items.filter((k) => k.recent).slice(0, 4), [items]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (k) =>
        k.kbName.toLowerCase().includes(q) ||
        k.displayName.toLowerCase().includes(q) ||
        k.description.toLowerCase().includes(q),
    );
  }, [items, query]);
  const filteredRecent = useMemo(() => filtered.filter((k) => k.recent), [filtered]);
  const filteredRest = useMemo(() => filtered.filter((k) => !k.recent), [filtered]);

  const sections = useMemo<{ label: string; items: KnowledgeBase[] }[]>(() => {
    if (query) return [{ label: tp("all", { count: filtered.length }), items: filtered }];
    if (scope === "recent") return [{ label: tp("recent"), items: filteredRecent }];
    if (scope === "starred" || scope === "archived") return [];
    const list: { label: string; items: KnowledgeBase[] }[] = [];
    if (filteredRecent.length > 0) list.push({ label: tp("recent"), items: filteredRecent });
    list.push({
      label: tp("all", { count: filtered.length }),
      items: filteredRecent.length > 0 ? filteredRest : filtered,
    });
    return list;
  }, [filtered, filteredRecent, filteredRest, query, scope, tp]);

  const isEmpty = sections.every((s) => s.items.length === 0);

  const select = (name: string) => {
    onChange(name);
    setOpen(false);
    setQuery("");
  };

  const renderRow = (k: KnowledgeBase) => {
    const active = k.kbName === value;
    const meta = [
      t("docsCount", { count: k.documents.toLocaleString() }),
      k.collections[0],
      t("updatedAgo", { time: formatRelative(k.updatedAgoMs, locale) }),
    ]
      .filter(Boolean)
      .join(" · ");
    return (
      <button
        key={k.kbName}
        type="button"
        onClick={() => select(k.kbName)}
        aria-pressed={active}
        className={`relative flex w-full items-center gap-[11px] rounded-lg py-2 pr-2.5 pl-3 text-left transition-colors ${
          active ? "bg-accent-soft" : "hover:bg-(--surface-muted)"
        }`}
      >
        {active ? (
          <span
            className="absolute top-3.5 left-0 h-[26px] w-[3px] rounded-full bg-accent"
            aria-hidden
          />
        ) : null}
        <KBBadge theme={k.theme} icon={k.icon} size={36} iconSize={18} radius={8} />
        <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
          <span className="flex items-center gap-[7px]">
            <span className="truncate font-mono text-[13px] font-semibold text-foreground">
              {k.kbName}
            </span>
            <span className="inline-flex shrink-0 items-center rounded bg-(--surface-muted) px-1.5 py-0.5 text-[10.5px] font-medium text-foreground-secondary">
              {k.displayName}
            </span>
          </span>
          <span className="truncate text-[11px] text-foreground-tertiary">{meta}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2.5">
          <span className="inline-flex items-center rounded-full bg-(--surface-muted) px-2 py-[3px] text-[11px] font-medium text-foreground-tertiary">
            {tp("nodes", { count: k.graphNodes })}
          </span>
          <span className="flex h-[18px] w-[18px] items-center justify-center">
            {active ? <Check className="h-[18px] w-[18px] text-accent" aria-hidden /> : null}
          </span>
        </span>
      </button>
    );
  };

  return (
    <div className="flex flex-col gap-2.5">
      {/* Trigger card */}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-surface p-3 text-left transition-colors hover:border-accent"
      >
        <span className="flex min-w-0 items-center gap-3">
          {current ? (
            <KBBadge
              theme={current.theme}
              icon={current.icon}
              size={40}
              iconSize={20}
              radius={10}
            />
          ) : (
            <span className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-(--surface-muted) text-foreground-secondary">
              <LayoutGrid className="h-5 w-5" aria-hidden />
            </span>
          )}
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="flex items-center gap-2">
              <span className="truncate text-sm font-semibold text-foreground">
                {current ? current.displayName : t("systemDefault")}
              </span>
              {current ? (
                <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent">
                  {t("current")}
                </span>
              ) : null}
            </span>
            <span className="truncate text-[11px] text-foreground-secondary">
              {current
                ? [
                    t("docsCount", { count: current.documents.toLocaleString() }),
                    current.collections[0],
                    t("updatedAgo", { time: formatRelative(current.updatedAgoMs, locale) }),
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : "default"}
            </span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="hidden items-center gap-1 rounded-full bg-(--surface-muted) px-2 py-1 text-[11px] font-medium text-foreground-secondary sm:inline-flex">
            <Layers className="h-3 w-3" aria-hidden />
            {t("totalLibs", { count: items.length })}
          </span>
          <ChevronsUpDown className="h-4 w-4 text-foreground-tertiary" aria-hidden />
        </span>
      </button>

      {/* Right-side Drawer */}
      <Drawer isOpen={open} onOpenChange={setOpen}>
        <Drawer.Backdrop className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
          <Drawer.Content
            placement="right"
            className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
          >
            <Drawer.Dialog className="w-full !max-w-none sm:w-1/3 sm:!max-w-[640px] data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
              <Drawer.Header className="flex flex-col gap-3 px-3.5 pt-3.5 pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-[30px] w-[30px] items-center justify-center rounded-lg bg-accent-soft">
                      <LibraryBig className="h-[17px] w-[17px] text-accent" aria-hidden />
                    </span>
                    <span className="flex flex-col gap-px">
                      <Drawer.Heading className="text-sm font-semibold text-foreground">
                        {tp("title")}
                      </Drawer.Heading>
                      <span className="font-mono text-[10px] text-foreground-tertiary">
                        {tp("single")}
                      </span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-(--surface-muted) px-2.5 py-1 text-[11px] font-semibold text-foreground-secondary">
                      <Layers className="h-3 w-3" aria-hidden />
                      {tp("count", { count: items.length })}
                    </span>
                    <Drawer.CloseTrigger
                      aria-label={tp("hint.close")}
                      className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-(--surface-muted) text-foreground-secondary transition-colors hover:text-foreground"
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                    </Drawer.CloseTrigger>
                  </div>
                </div>

                <div className="flex h-10 items-center gap-2.5 rounded-xl border border-border bg-surface px-3 focus-within:border-field-border-focus">
                  <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={tp("searchPlaceholder")}
                    className="w-full min-w-0 bg-transparent text-[13px] text-foreground outline-none placeholder:text-foreground-secondary"
                  />
                  <span className="rounded border border-border px-[7px] py-0.5 font-mono text-[11px] font-semibold text-foreground-tertiary">
                    esc
                  </span>
                </div>

                <div className="flex h-[34px] items-stretch gap-0.5 rounded-lg bg-(--surface-muted) p-0.5">
                  {SCOPES.map(({ key, icon: Icon }) => {
                    const on = scope === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setScope(key)}
                        aria-pressed={on}
                        className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2.5 text-[12px] transition-colors ${
                          on
                            ? "bg-surface font-semibold text-foreground shadow-sm"
                            : "font-medium text-foreground-secondary hover:text-foreground"
                        }`}
                      >
                        <Icon className="h-[13px] w-[13px]" aria-hidden />
                        {tp(`scope.${key}`)}
                      </button>
                    );
                  })}
                </div>
              </Drawer.Header>

              {/* Body */}
              <Drawer.Body className="min-h-0 flex-1 overflow-y-auto px-2 pt-2 pb-2.5">
                {isEmpty ? (
                  <p className="px-2 py-10 text-center text-sm text-foreground-tertiary">
                    {tp("empty")}
                  </p>
                ) : (
                  sections.map((sec, i) => (
                    <Fragment key={sec.label}>
                      {i > 0 ? (
                        <div className="px-3 py-[5px]">
                          <div className="h-px bg-border" />
                        </div>
                      ) : null}
                      <p className="px-3 pt-[7px] pb-[3px] text-[11px] font-semibold tracking-[0.3px] text-foreground-tertiary">
                        {sec.label}
                      </p>
                      {sec.items.map(renderRow)}
                    </Fragment>
                  ))
                )}
              </Drawer.Body>

              {/* Footer */}
              <Drawer.Footer className="flex h-11 items-center gap-3.5 border-t border-border bg-(--surface-muted) px-3.5">
                <div className="flex flex-1 items-center gap-3.5">
                  <Hint keys={["↑", "↓"]} label={tp("hint.nav")} />
                  <Hint keys={["↵"]} label={tp("hint.select")} />
                  <Hint keys={["esc"]} label={tp("hint.close")} />
                </div>
                <Link
                  href="/kb"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-1.5 text-[12px] font-semibold text-accent hover:underline"
                >
                  <Settings2 className="h-[13px] w-[13px]" aria-hidden />
                  {tp("manage")}
                </Link>
              </Drawer.Footer>
            </Drawer.Dialog>
          </Drawer.Content>
        </Drawer.Backdrop>
      </Drawer>

      {recent.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 text-[11px] text-foreground-tertiary">
            <Clock className="h-3 w-3" aria-hidden />
            {t("recent")}
          </span>
          {recent.map((k) => {
            const active = k.kbName === value;
            return (
              <button
                key={k.kbName}
                type="button"
                onClick={() => select(k.kbName)}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] font-medium transition-colors ${
                  active
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border bg-surface text-foreground-secondary hover:border-accent/40"
                }`}
              >
                <KBBadge theme={k.theme} icon={k.icon} size={16} iconSize={10} radius={4} />
                <span className="font-mono">{k.kbName}</span>
                <span className="text-foreground-tertiary">· {k.displayName}</span>
              </button>
            );
          })}
          {items.length > recent.length ? (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-1 text-[11px] font-medium text-foreground-secondary transition-colors hover:border-accent/40"
            >
              <Search className="h-3 w-3" aria-hidden />
              {t("searchAll", { count: items.length - recent.length })}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
