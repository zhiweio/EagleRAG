"use client";

import { PIPELINE_STYLES } from "@/components/kb/kb-visuals";
import { cn } from "@/components/ui";
import type { KnowledgeBase } from "@/lib/kb/types";
import { useFilterStore } from "@/lib/stores/filterStore";
import { useKBStore } from "@/lib/stores/kbStore";
import { Popover } from "@heroui/react";
import {
  BookOpen,
  Check,
  ChevronDown,
  LayoutList,
  Loader2,
  RefreshCw,
  Search,
  Shuffle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useRef, useState } from "react";

const PHASE_DOT: Record<string, string> = {
  pending: "bg-warning",
  running: "bg-accent",
  success: "bg-success",
  failed: "bg-danger",
};

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

interface FilterOption {
  value: string;
  label: string;
  count: number;
  marker: ReactNode;
}

interface FilterButtonProps {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  badge?: number;
  title: string;
  allLabel: string;
  allActive: boolean;
  onAll: () => void;
  options: FilterOption[];
  isSelected: (value: string) => boolean;
  onSelect: (value: string) => void;
}

function FilterButton({
  icon: Icon,
  label,
  active,
  badge,
  title,
  allLabel,
  allActive,
  onAll,
  options,
  isSelected,
  onSelect,
}: FilterButtonProps) {
  const totalCount = options.reduce((sum, o) => sum + o.count, 0);
  return (
    <Popover>
      <Popover.Trigger>
        <div
          className={cn(
            "inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium transition-colors",
            active
              ? "bg-accent-soft text-accent"
              : "border border-border bg-surface text-foreground-secondary hover:border-accent/40",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
          <span>{label}</span>
          {badge ? (
            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-foreground">
              {badge}
            </span>
          ) : null}
          <ChevronDown className="h-3.5 w-3.5" aria-hidden />
        </div>
      </Popover.Trigger>
      <Popover.Content className="w-64 p-0">
        <Popover.Dialog aria-label={title}>
          <div className="flex flex-col">
            <div className="border-b border-border px-3 py-2.5">
              <span className="text-xs font-semibold text-foreground-secondary">{title}</span>
            </div>
            <div className="flex flex-col gap-0.5 p-1.5">
              <button
                type="button"
                onClick={onAll}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-(--surface-muted)"
              >
                <span className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{allLabel}</span>
                  <span className="text-xs text-foreground-tertiary">{totalCount}</span>
                </span>
                {allActive ? <Check className="h-4 w-4 text-accent" aria-hidden /> : null}
              </button>
              {options.map((option) => {
                const selected = isSelected(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => onSelect(option.value)}
                    className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-(--surface-muted)"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      {option.marker}
                      <span className="truncate font-medium text-foreground">{option.label}</span>
                      <span className="shrink-0 text-xs text-foreground-tertiary">
                        {option.count}
                      </span>
                    </span>
                    {selected ? (
                      <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}

interface TaskToolbarProps {
  onRefresh: () => void;
  refreshing: boolean;
  kbItems: KnowledgeBase[];
  /** Per-dimension counts (derived from the current task list). */
  counts: {
    kb: Record<string, number>;
    pipeline: Record<string, number>;
    status: Record<string, number>;
  };
}

/**
 * Refresh button with guaranteed-visible spin animation.
 *
 * The parent's `refreshing` flag (from react-query's `isFetching`) can flip on/off
 * within a single frame when the cache is warm, making `animate-spin` invisible.
 * We pin the spin state for a minimum window after each click so the user always
 * sees feedback, then surface a brief check-mark when the refresh settles.
 */
function RefreshButton({
  onRefresh,
  refreshing,
  label,
}: {
  onRefresh: () => void;
  refreshing: boolean;
  label: string;
}) {
  // Local spin state pinned to a min duration so the animation is always visible.
  const [spinning, setSpinning] = useState(false);
  // Brief "done" confirmation shown after a refresh completes.
  const [done, setDone] = useState(false);
  const minSpinTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tracks the fetch cycle: set true on click, cleared when `refreshing` goes false.
  const watching = useRef(false);

  // When the parent signals fetching is underway, keep spinning.
  useEffect(() => {
    if (refreshing) {
      watching.current = true;
      setSpinning(true);
    } else if (watching.current) {
      // Fetching just ended — only fire the "done" pulse if we passed the min window.
      watching.current = false;
      if (minSpinTimer.current) {
        // Let the min-window timer handle the transition to "done".
      } else {
        setSpinning(false);
        setDone(true);
        doneTimer.current = setTimeout(() => setDone(false), 900);
      }
    }
  }, [refreshing]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (minSpinTimer.current) clearTimeout(minSpinTimer.current);
      if (doneTimer.current) clearTimeout(doneTimer.current);
    };
  }, []);

  const handleClick = () => {
    // Always show the spin for at least 600ms, even if the fetch resolves instantly.
    setSpinning(true);
    setDone(false);
    minSpinTimer.current = setTimeout(() => {
      minSpinTimer.current = null;
      // If the fetch already finished during the min window, transition to "done".
      if (!watching.current) {
        setSpinning(false);
        setDone(true);
        doneTimer.current = setTimeout(() => setDone(false), 900);
      }
    }, 600);
    onRefresh();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={label}
      aria-busy={spinning}
      disabled={spinning}
      className={cn(
        "group relative inline-flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border transition-all duration-200 active:scale-90",
        spinning
          ? "border-accent/30 bg-accent-soft text-accent"
          : done
            ? "border-success/40 bg-success-soft text-success"
            : "border-border bg-surface text-foreground-secondary hover:border-accent/40 hover:text-accent",
      )}
    >
      {/* Rotating ring track — visible only while spinning */}
      {spinning ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : done ? (
        <Check
          className="h-4 w-4 animate-[kbRowIn_220ms_cubic-bezier(0.16,1,0.3,1)_both]"
          aria-hidden
        />
      ) : (
        <RefreshCw
          className="h-4 w-4 transition-transform duration-300 group-hover:-rotate-45"
          aria-hidden
        />
      )}
    </button>
  );
}

export function TaskToolbar({ onRefresh, refreshing, kbItems, counts }: TaskToolbarProps) {
  const t = useTranslations("ingest");
  const { taskFilter, setTaskFilter } = useFilterStore();
  const { query, pipelines, statuses } = taskFilter;
  const { kbName, setKbName } = useKBStore();

  const selectedKb = kbItems.find((k) => k.kbName === kbName);
  const statusPhases = ["pending", "running", "success", "failed"] as const;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-56 flex-1">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-foreground-tertiary"
          aria-hidden
        />
        <input
          value={query}
          onChange={(e) => setTaskFilter("query", e.target.value)}
          placeholder={t("toolbar.search")}
          aria-label={t("toolbar.search")}
          className="h-9 w-full rounded-lg border border-border bg-surface pr-14 pl-9 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-tertiary focus:border-field-border-focus"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded border border-border bg-(--surface-muted) px-1.5 py-0.5 font-mono text-[10px] text-foreground-tertiary">
          ⌘ K
        </kbd>
      </div>

      <FilterButton
        icon={BookOpen}
        label={selectedKb ? selectedKb.displayName : t("toolbar.allKB")}
        active
        title={t("filters.kbTitle")}
        allLabel={t("filters.allKB")}
        allActive={!kbName}
        onAll={() => setKbName("")}
        options={kbItems.map((k) => ({
          value: k.kbName,
          label: k.displayName,
          count: counts.kb[k.kbName] ?? 0,
          marker: (
            <span
              aria-hidden
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: "var(--accent)" }}
            />
          ),
        }))}
        isSelected={(v) => v === kbName}
        onSelect={(v) => setKbName(v === kbName ? "" : v)}
      />

      <FilterButton
        icon={Shuffle}
        label={t("toolbar.allPipeline")}
        badge={pipelines.length}
        title={t("filters.pipelineTitle")}
        allLabel={t("filters.allPipeline")}
        allActive={pipelines.length === 0}
        onAll={() => setTaskFilter("pipelines", [])}
        options={(["knowhere", "pixelrag"] as const).map((kind) => ({
          value: kind,
          label: t(`filters.${kind}`),
          count: counts.pipeline[kind] ?? 0,
          marker: (
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
              style={{ backgroundColor: PIPELINE_STYLES[kind].color }}
            />
          ),
        }))}
        isSelected={(v) => pipelines.includes(v)}
        onSelect={(v) => setTaskFilter("pipelines", toggleValue(pipelines, v))}
      />

      <FilterButton
        icon={LayoutList}
        label={t("toolbar.allStatus")}
        badge={statuses.length}
        title={t("filters.statusTitle")}
        allLabel={t("filters.allStatus")}
        allActive={statuses.length === 0}
        onAll={() => setTaskFilter("statuses", [])}
        options={statusPhases.map((phase) => ({
          value: phase,
          label: t(`status.${phase}`),
          count: counts.status[phase] ?? 0,
          marker: (
            <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", PHASE_DOT[phase])} />
          ),
        }))}
        isSelected={(v) => statuses.includes(v)}
        onSelect={(v) => setTaskFilter("statuses", toggleValue(statuses, v))}
      />

      <RefreshButton onRefresh={onRefresh} refreshing={refreshing} label={t("toolbar.refresh")} />
    </div>
  );
}
