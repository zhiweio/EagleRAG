"use client";

import { cn } from "@/components/ui";
import type { LucideIcon } from "lucide-react";
import { Loader2 } from "lucide-react";

/**
 * DrawerActionButton — the ghost maintenance buttons at the bottom of the
 * Milvus / Knowhere dashboards (design frames 05 & 13).
 *
 * - `loading`: shows a spinning loader icon and disables interaction.
 * - `disabled`: greys out and disables interaction (e.g. while a mutually-exclusive operation is in progress).
 */
export function DrawerActionButton({
  icon: Icon,
  label,
  onClick,
  className,
  loading = false,
  disabled = false,
}: {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  className?: string;
  loading?: boolean;
  disabled?: boolean;
}) {
  const isDisabled = loading || disabled;
  return (
    <button
      type="button"
      onClick={isDisabled ? undefined : onClick}
      disabled={isDisabled}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm font-medium text-foreground-secondary transition-colors hover:bg-background-secondary hover:text-foreground",
        isDisabled &&
          "cursor-not-allowed opacity-50 hover:bg-surface hover:text-foreground-secondary",
        className,
      )}
    >
      {loading ? (
        <Loader2 size={15} strokeWidth={2} className="animate-spin" aria-hidden />
      ) : (
        <Icon size={15} strokeWidth={2} aria-hidden />
      )}
      {label}
    </button>
  );
}
