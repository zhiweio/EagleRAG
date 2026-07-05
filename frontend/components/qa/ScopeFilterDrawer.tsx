"use client";

import { useDocuments } from "@/lib/hooks/useDocuments";
import { useKnowledgeBases } from "@/lib/hooks/useKB";
import { useTags } from "@/lib/hooks/useTags";
import {
  type ScopeRef,
  type ScopeSelectionState,
  scopeCount,
  useScopeStore,
} from "@/lib/stores/scopeStore";
import { Drawer } from "@heroui/react";
import {
  Check,
  FileText,
  Filter,
  LibraryBig,
  Search,
  SlidersHorizontal,
  Tag,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";

type Tab = "all" | "kb" | "doc" | "tag";
type Dimension = "kbNames" | "documents" | "tags";

interface ScopeFilterDrawerProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

const EMPTY_DRAFT: ScopeSelectionState = { kbNames: [], documents: [], tags: [] };

/** Toggle a ref in/out of a list, matching by id. */
function toggleRef(list: ScopeRef[], ref: ScopeRef): ScopeRef[] {
  return list.some((x) => x.id === ref.id) ? list.filter((x) => x.id !== ref.id) : [...list, ref];
}

/**
 * Advanced scope filter drawer (right, 1/3 width). Lets the user multi-select
 * across knowledge bases, documents and tags — combined as a union (OR) — using
 * a draft-then-apply pattern: edits stay local until "Apply" commits them to the
 * scope store; closing without applying discards the draft.
 */
export function ScopeFilterDrawer({ isOpen, onOpenChange }: ScopeFilterDrawerProps) {
  const t = useTranslations("qa.scopeDrawer");
  const setScope = useScopeStore((s) => s.setScope);

  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<ScopeSelectionState>(EMPTY_DRAFT);

  // Seed the draft from the committed selection each time the drawer opens.
  // Read the store snapshot directly so the effect only fires on open transitions.
  useEffect(() => {
    if (!isOpen) return;
    const { kbNames, documents, tags } = useScopeStore.getState();
    setDraft({ kbNames, documents, tags });
    setQuery("");
    setTab("all");
  }, [isOpen]);

  const q = query.trim();
  const kbQuery = useKnowledgeBases({ query: q || undefined, sort: "name", limit: 200 });
  const docQuery = useDocuments({ q: q || undefined, limit: 30 });
  const tagQuery = useTags({ q: q || undefined, limit: 30 });

  const kbItems = useMemo(() => kbQuery.data?.items ?? [], [kbQuery.data?.items]);
  const docItems = useMemo(() => docQuery.data?.items ?? [], [docQuery.data?.items]);
  const tagItems = useMemo(() => tagQuery.data?.items ?? [], [tagQuery.data?.items]);

  const selectedCount = scopeCount(draft);

  const isSelected = (dim: Dimension, id: string) => draft[dim].some((x) => x.id === id);
  const toggle = (dim: Dimension, ref: ScopeRef) =>
    setDraft((prev) => ({ ...prev, [dim]: toggleRef(prev[dim], ref) }));
  const remove = (dim: Dimension, id: string) =>
    setDraft((prev) => ({ ...prev, [dim]: prev[dim].filter((x) => x.id !== id) }));

  const apply = () => {
    setScope(draft);
    onOpenChange(false);
  };

  const tabs: { key: Tab; label: string; icon: typeof LibraryBig }[] = [
    { key: "all", label: t("tabAll"), icon: SlidersHorizontal },
    { key: "kb", label: t("tabKb"), icon: LibraryBig },
    { key: "doc", label: t("tabDoc"), icon: FileText },
    { key: "tag", label: t("tabTag"), icon: Tag },
  ];

  const showKb = tab === "all" || tab === "kb";
  const showDoc = tab === "all" || tab === "doc";
  const showTag = tab === "all" || tab === "tag";
  function cap<T>(list: T[]): T[] {
    return tab === "all" ? list.slice(0, 5) : list;
  }

  return (
    <Drawer isOpen={isOpen} onOpenChange={onOpenChange}>
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
                    <Filter className="h-[17px] w-[17px] text-accent-soft-foreground" aria-hidden />
                  </span>
                  <div className="flex flex-col gap-px">
                    <Drawer.Heading className="text-sm font-semibold text-foreground">
                      {t("title")}
                    </Drawer.Heading>
                    <span className="text-[10px] text-foreground-tertiary">{t("subtitle")}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="flex items-center gap-1.5 rounded-full bg-(--surface-muted) px-2.5 py-1 text-[11px] font-semibold text-foreground-secondary">
                    {t("selected", { count: selectedCount })}
                  </span>
                  <Drawer.CloseTrigger
                    aria-label={t("close")}
                    className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-(--surface-muted) text-foreground-secondary transition-colors hover:bg-(--separator)"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </Drawer.CloseTrigger>
                </div>
              </div>

              {/* Unified search */}
              <div className="flex h-10 items-center gap-2.5 rounded-xl border border-border bg-surface px-3 focus-within:border-field-border-focus">
                <Search className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                  className="w-full min-w-0 bg-transparent text-[13px] text-foreground outline-none placeholder:text-foreground-secondary"
                />
              </div>

              {/* Segmented tabs */}
              <div className="flex h-[34px] items-center gap-0.5 rounded-lg bg-(--surface-muted) p-0.5">
                {tabs.map((s) => {
                  const active = tab === s.key;
                  const Icon = s.icon;
                  return (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setTab(s.key)}
                      aria-pressed={active}
                      className={`flex h-full flex-1 items-center justify-center gap-1.5 rounded-md text-xs font-semibold transition-colors ${
                        active
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

            <Drawer.Body className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
              {/* Active scope */}
              <section className="flex flex-col gap-1.5">
                <p className="px-1 text-[11px] font-semibold tracking-[0.3px] text-foreground-tertiary">
                  {t("activeScope", { count: selectedCount })}
                </p>
                {selectedCount === 0 ? (
                  <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-foreground-tertiary">
                    {t("activeEmpty")}
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {draft.kbNames.map((k) => (
                      <ActiveChip
                        key={`kb-${k.id}`}
                        icon={LibraryBig}
                        label={k.label}
                        removeLabel={t("remove")}
                        onRemove={() => remove("kbNames", k.id)}
                      />
                    ))}
                    {draft.documents.map((d) => (
                      <ActiveChip
                        key={`doc-${d.id}`}
                        icon={FileText}
                        label={d.label}
                        removeLabel={t("remove")}
                        onRemove={() => remove("documents", d.id)}
                      />
                    ))}
                    {draft.tags.map((tg) => (
                      <ActiveChip
                        key={`tag-${tg.id}`}
                        icon={Tag}
                        label={tg.label}
                        removeLabel={t("remove")}
                        onRemove={() => remove("tags", tg.id)}
                      />
                    ))}
                  </div>
                )}
              </section>

              <div className="h-px bg-(--separator)" />

              {/* Suggestions */}
              <p className="px-1 text-[11px] font-semibold tracking-[0.3px] text-foreground-tertiary">
                {t("suggestions")}
              </p>

              {showKb ? (
                <SuggestionSection title={t("sectionKb")}>
                  {cap(kbItems).length === 0 ? (
                    <EmptyRow text={t("empty")} />
                  ) : (
                    cap(kbItems).map((k) => (
                      <SuggestionRow
                        key={k.kbName}
                        icon={LibraryBig}
                        title={k.displayName || k.kbName}
                        meta={t("kbMeta", { docs: k.documents, nodes: k.graphNodes })}
                        selected={isSelected("kbNames", k.kbName)}
                        onToggle={() =>
                          toggle("kbNames", {
                            id: k.kbName,
                            label: k.displayName || k.kbName,
                            meta: k.kbName,
                          })
                        }
                      />
                    ))
                  )}
                </SuggestionSection>
              ) : null}

              {showDoc ? (
                <SuggestionSection title={t("sectionDoc")}>
                  {cap(docItems).length === 0 ? (
                    <EmptyRow text={t("empty")} />
                  ) : (
                    cap(docItems).map((d) => (
                      <SuggestionRow
                        key={d.document_id}
                        icon={FileText}
                        title={d.name}
                        meta={t("docMeta", { kb: d.kb_name ?? "", nodes: d.chunk_count ?? 0 })}
                        selected={isSelected("documents", d.document_id)}
                        onToggle={() =>
                          toggle("documents", {
                            id: d.document_id,
                            label: d.name,
                            meta: d.kb_name,
                          })
                        }
                      />
                    ))
                  )}
                </SuggestionSection>
              ) : null}

              {showTag ? (
                <SuggestionSection title={t("sectionTag")}>
                  {cap(tagItems).length === 0 ? (
                    <EmptyRow text={t("empty")} />
                  ) : (
                    cap(tagItems).map((tg) => (
                      <SuggestionRow
                        key={tg.tag}
                        icon={Tag}
                        title={tg.tag}
                        meta={t("tagMeta", { nodes: tg.node_count ?? 0, kb: tg.kb_count ?? 0 })}
                        selected={isSelected("tags", tg.tag)}
                        onToggle={() => toggle("tags", { id: tg.tag, label: tg.tag })}
                      />
                    ))
                  )}
                </SuggestionSection>
              ) : null}
            </Drawer.Body>

            <Drawer.Footer className="flex items-center justify-between gap-3 border-t border-separator px-3.5 py-2.5">
              <button
                type="button"
                onClick={() => setDraft(EMPTY_DRAFT)}
                className="rounded-lg px-3 py-2 text-xs font-semibold text-foreground-secondary transition-colors hover:bg-(--surface-muted)"
              >
                {t("clear")}
              </button>
              <button
                type="button"
                onClick={apply}
                className="flex-1 rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-accent-foreground transition-opacity hover:opacity-90"
              >
                {t("apply")}
              </button>
            </Drawer.Footer>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}

function SuggestionSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-0.5">
      <p className="px-1 pb-0.5 text-[10.5px] font-medium uppercase tracking-[0.4px] text-foreground-tertiary">
        {title}
      </p>
      {children}
    </section>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <p className="px-3 py-2 text-xs text-foreground-tertiary">{text}</p>;
}

function SuggestionRow({
  icon: Icon,
  title,
  meta,
  selected,
  onToggle,
}: {
  icon: typeof LibraryBig;
  title: string;
  meta: string;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
        selected ? "bg-accent-soft" : "hover:bg-(--surface-muted)"
      }`}
    >
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
          selected ? "bg-accent/15 text-accent" : "bg-(--surface-muted) text-foreground-secondary"
        }`}
      >
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-[13px] font-medium text-foreground">{title}</span>
        <span className="truncate text-[11px] text-foreground-tertiary">{meta}</span>
      </span>
      <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
        {selected ? <Check className="h-[18px] w-[18px] text-accent" aria-hidden /> : null}
      </span>
    </button>
  );
}

function ActiveChip({
  icon: Icon,
  label,
  removeLabel,
  onRemove,
}: {
  icon: typeof LibraryBig;
  label: string;
  removeLabel: string;
  onRemove: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent">
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      <span className="max-w-40 truncate">{label}</span>
      <button
        type="button"
        aria-label={removeLabel}
        onClick={onRemove}
        className="ml-0.5 inline-flex items-center opacity-70 transition-opacity hover:opacity-100"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}
