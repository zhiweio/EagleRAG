"use client";

import { useDeleteSession, useSessions } from "@/lib/hooks/useQA";
import type { SessionSummary } from "@/lib/types";
import { Drawer, Spinner } from "@heroui/react";
import { Plus, Search, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import {
  filterSessions,
  formatHistoryTime,
  groupSessions,
  sessionTagLabel,
  tagStyleFor,
} from "./history-utils";

interface HistoryDrawerProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  currentSessionId: string | null;
  /** Knowledge-base filter applied to the session list (null = all). */
  kbName?: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteError?: (err: unknown) => void;
}

/**
 * HistoryDrawer — session timeline from the design spec: search, time-grouped
 * rows with scope/kb tags, and a circular new-chat affordance.
 */
export function HistoryDrawer({
  isOpen,
  onOpenChange,
  currentSessionId,
  kbName,
  onSelectSession,
  onNewSession,
  onDeleteError,
}: HistoryDrawerProps) {
  const t = useTranslations("qa.history");
  const locale = useLocale();
  const [query, setQuery] = useState("");

  const sessionsQuery = useSessions({ limit: 50, kb_name: kbName || undefined });
  const deleteSession = useDeleteSession();

  const sessions = sessionsQuery.data?.items ?? [];
  const loading = sessionsQuery.isLoading;
  const failed = Boolean(sessionsQuery.error);

  const filtered = useMemo(() => filterSessions(sessions, query), [sessions, query]);
  const grouped = useMemo(() => groupSessions(filtered), [filtered]);

  const timeOpts = useMemo(
    () => ({
      locale,
      todayLabel: (d: Date) =>
        d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false }),
      daysAgo: (count: number) => t("daysAgo", { count }),
    }),
    [locale, t],
  );

  function handleSelect(id: string) {
    onSelectSession(id);
    onOpenChange(false);
  }

  function handleNew() {
    onNewSession();
    onOpenChange(false);
  }

  function handleDelete(id: string) {
    deleteSession.mutate(id, {
      onError: (err: unknown) => onDeleteError?.(err),
    });
  }

  const sections: { key: keyof typeof grouped; label: string }[] = [
    { key: "today", label: t("groupToday") },
    { key: "week", label: t("groupWeek") },
    { key: "older", label: t("groupOlder") },
  ];

  const hasResults = filtered.length > 0;

  return (
    <Drawer isOpen={isOpen} onOpenChange={onOpenChange}>
      <Drawer.Backdrop className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]">
        <Drawer.Content
          placement="left"
          className="data-[entering]:duration-300 data-[entering]:ease-[cubic-bezier(0.32,0.72,0,1)] data-[exiting]:duration-200 data-[exiting]:ease-[cubic-bezier(0.7,0,0.84,0)]"
        >
          <Drawer.Dialog className="w-full max-w-[85vw] bg-surface text-foreground sm:w-[320px] data-[entering]:duration-300 data-[exiting]:duration-200">
            <Drawer.Header className="flex flex-col gap-3 border-b border-separator px-4 pb-3 pt-4">
              <div className="flex items-center justify-between">
                <Drawer.Heading className="font-semibold text-base text-foreground tracking-tight">
                  {t("title")}
                </Drawer.Heading>
                <button
                  type="button"
                  onClick={handleNew}
                  aria-label={t("new")}
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-[0_2px_6px_0_rgba(4,133,247,0.28)] transition-opacity hover:opacity-90"
                >
                  <Plus className="h-[18px] w-[18px]" strokeWidth={2.2} aria-hidden />
                </button>
              </div>

              <div className="flex h-10 items-center gap-2.5 rounded-xl bg-(--surface-muted) px-3 focus-within:ring-2 focus-within:ring-accent/20">
                <Search
                  className="h-4 w-4 shrink-0 text-foreground-secondary"
                  strokeWidth={2}
                  aria-hidden
                />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                  className="w-full min-w-0 bg-transparent text-[13px] text-foreground outline-none placeholder:text-foreground-secondary"
                />
              </div>
            </Drawer.Header>

            <Drawer.Body className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
              {loading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-foreground-secondary text-sm">
                  <Spinner size="sm" />
                  <span>{t("loading")}</span>
                </div>
              ) : failed ? (
                <EmptyHint text={t("loadError")} />
              ) : !hasResults ? (
                <EmptyHint text={query.trim() ? t("noResults") : t("empty")} />
              ) : (
                <div className="flex flex-col gap-4">
                  {sections.map(({ key, label }) => {
                    const items = grouped[key];
                    if (items.length === 0) return null;
                    return (
                      <section key={key}>
                        <p className="mb-1.5 px-1 font-medium text-[11px] text-foreground-tertiary tracking-wide">
                          {label}
                        </p>
                        <ul className="flex flex-col gap-1">
                          {items.map((s) => (
                            <HistoryRow
                              key={s.session_id}
                              session={s}
                              active={s.session_id === currentSessionId}
                              timeLabel={formatHistoryTime(s.updated_at ?? s.created_at, timeOpts)}
                              tagLabel={sessionTagLabel(s)}
                              onSelect={() => handleSelect(s.session_id)}
                              onDelete={() => handleDelete(s.session_id)}
                              deleteLabel={t("delete")}
                              deleting={deleteSession.isPending}
                            />
                          ))}
                        </ul>
                      </section>
                    );
                  })}
                </div>
              )}
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}

function HistoryRow({
  session,
  active,
  timeLabel,
  tagLabel,
  onSelect,
  onDelete,
  deleteLabel,
  deleting,
}: {
  session: SessionSummary;
  active: boolean;
  timeLabel: string;
  tagLabel: string | null;
  onSelect: () => void;
  onDelete: () => void;
  deleteLabel: string;
  deleting: boolean;
}) {
  const title = session.title || session.session_id;

  return (
    <li>
      <div
        className={`group relative flex items-start gap-2 rounded-xl border px-3 py-2.5 transition-colors ${
          active ? "border-accent bg-accent-soft" : "border-transparent hover:bg-(--surface-muted)"
        }`}
      >
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left"
        >
          <span
            className={`line-clamp-2 text-[13px] leading-snug ${
              active ? "font-semibold text-accent" : "font-medium text-foreground"
            }`}
          >
            {title}
          </span>
          {timeLabel ? (
            <span
              className={`font-mono text-[11px] ${
                active ? "text-accent/75" : "text-foreground-tertiary"
              }`}
            >
              {timeLabel}
            </span>
          ) : null}
        </button>

        {tagLabel ? (
          <span
            className={`mt-0.5 inline-flex max-w-[5.5rem] shrink-0 truncate rounded-full px-2 py-0.5 font-medium text-[10.5px] ${tagStyleFor(tagLabel)}`}
            title={tagLabel}
          >
            {tagLabel}
          </span>
        ) : null}

        <button
          type="button"
          aria-label={deleteLabel}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          disabled={deleting}
          className="absolute top-1.5 right-1.5 rounded-md p-0.5 text-foreground-tertiary opacity-0 transition-opacity hover:bg-surface hover:text-danger group-hover:opacity-100 focus:opacity-100"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </li>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="rounded-xl border border-border border-dashed px-4 py-10 text-center text-foreground-tertiary text-xs leading-relaxed">
      {text}
    </p>
  );
}
