"use client";

import { Plus } from "lucide-react";

/** 08 · "New knowledge base" dashed ghost card in the KB management grid. */
export function KBGhostCard({
  title,
  sub,
  onClick,
}: { title: string; sub: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-[200px] flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed border-border p-[18px] text-center transition-colors hover:border-accent/50 hover:bg-accent-soft/40"
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-background-secondary text-foreground-secondary">
        <Plus className="h-[22px] w-[22px]" aria-hidden />
      </span>
      <span className="text-sm font-semibold text-foreground-secondary">{title}</span>
      <span className="text-xs text-foreground-tertiary">{sub}</span>
    </button>
  );
}
