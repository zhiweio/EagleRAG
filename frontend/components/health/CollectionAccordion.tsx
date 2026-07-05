"use client";

import { cn } from "@/components/ui";
import type { CollectionRow } from "@/lib/health/types";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FieldBox } from "./drawer-parts";

/**
 * CollectionAccordion — expandable list of Milvus collections (frame 05) or
 * Knowhere KB partitions (frame 13). The first row is expanded by default and
 * reveals the Dim / Metric / Index field boxes plus a meta line.
 *
 * `ns` selects the translation namespace so the same component serves both the
 * Milvus collection view and the Knowhere partition view.
 */
export function CollectionAccordion({
  rows,
  ns,
  countLabel,
}: {
  rows: CollectionRow[];
  ns: "milvusDrawer" | "knowhereDrawer" | "storageDrawer";
  /** How to render the entity/node count on the right of each row header. */
  countLabel: (count: string) => string;
}) {
  const t = useTranslations("health");
  const [openName, setOpenName] = useState<string | null>(rows[0]?.name ?? null);

  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => {
        const open = openName === row.name;
        return (
          <div
            key={row.name}
            className="overflow-hidden rounded-xl border border-border bg-surface"
          >
            <button
              type="button"
              onClick={() => setOpenName(open ? null : row.name)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            >
              <span className="flex min-w-0 items-center gap-2">
                <ChevronDown
                  size={16}
                  strokeWidth={2}
                  aria-hidden
                  className={cn(
                    "shrink-0 text-foreground-tertiary transition-transform",
                    open ? "rotate-0" : "-rotate-90",
                  )}
                />
                <span className="truncate font-mono text-sm font-semibold text-foreground">
                  {row.name}
                </span>
                <span className="inline-flex shrink-0 items-center rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent-soft-foreground">
                  {t(`${ns}.tag.${row.tagKey}`)}
                </span>
              </span>
              <span className="shrink-0 font-mono text-xs text-foreground-tertiary">
                {countLabel(row.count)}
              </span>
            </button>

            {open ? (
              <div className="flex flex-col gap-3 border-t border-border px-4 py-3">
                <div className="grid grid-cols-3 gap-2">
                  {row.fields.map((f) => (
                    <FieldBox
                      key={f.labelKey}
                      label={t(`milvusDrawer.fieldLabels.${f.labelKey}`)}
                      value={f.value}
                    />
                  ))}
                </div>
                <p className="font-mono text-[11px] leading-relaxed text-foreground-secondary">
                  {row.meta}
                </p>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
