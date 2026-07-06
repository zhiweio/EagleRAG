"use client";

import type { KBSort } from "@/lib/hooks/useKB";
import { Button, Popover } from "@heroui/react";
import { ArrowUpDown, Check, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

const SORT_OPTIONS: { value: KBSort; labelKey: "sortRecent" | "sortName" | "sortSize" }[] = [
  { value: "recent", labelKey: "sortRecent" },
  { value: "name", labelKey: "sortName" },
  { value: "size", labelKey: "sortSize" },
];

interface KBSortPickerProps {
  value: KBSort;
  onChange: (value: KBSort) => void;
}

export function KBSortPicker({ value, onChange }: KBSortPickerProps) {
  const t = useTranslations("kb.management");
  const [open, setOpen] = useState(false);

  const current = SORT_OPTIONS.find((item) => item.value === value) ?? SORT_OPTIONS[0];

  function onSelect(next: KBSort) {
    setOpen(false);
    if (next !== value) onChange(next);
  }

  return (
    <Popover isOpen={open} onOpenChange={setOpen}>
      <Button
        aria-label={t("sort")}
        aria-expanded={open}
        variant="tertiary"
        className="inline-flex h-[42px] items-center gap-2 rounded-xl border border-border bg-surface px-3.5 text-sm font-medium text-foreground shadow-[0_1px_3px_0_rgba(0,0,0,0.04)] hover:bg-background-secondary"
      >
        <ArrowUpDown className="h-[15px] w-[15px] shrink-0 text-foreground-secondary" aria-hidden />
        <span className="whitespace-nowrap">{t(current.labelKey)}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-foreground-tertiary transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </Button>
      <Popover.Content className="min-w-56 p-0" placement="bottom end">
        <Popover.Dialog aria-label={t("sort")}>
          <div className="flex flex-col gap-0.5 p-1.5">
            {SORT_OPTIONS.map((item) => {
              const selected = item.value === value;
              return (
                <button
                  key={item.value}
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelect(item.value)}
                  className={`flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${
                    selected
                      ? "bg-accent-soft text-accent"
                      : "text-foreground hover:bg-(--surface-muted)"
                  }`}
                >
                  <span className="font-medium">{t(item.labelKey)}</span>
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
