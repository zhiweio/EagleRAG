import { cn } from "@/lib/utils";
import { type LucideIcon, ScanSearch } from "lucide-react";

const SIZES = {
  sm: { box: 32, icon: 17 },
  lg: { box: 48, icon: 24 },
} as const;

export type QAAvatarSize = keyof typeof SIZES;

interface QAAvatarProps {
  size?: QAAvatarSize;
  /** Larger rounded rect for the empty-state hero. */
  hero?: boolean;
  className?: string;
  icon?: LucideIcon;
}

/**
 * QAAvatar — assistant mark for Q&A. ``ScanSearch`` reads as retrieval over
 * documents (RAG) without the generic Sparkles gradient or product logo tile.
 */
export function QAAvatar({
  size = "sm",
  hero = false,
  className,
  icon: Icon = ScanSearch,
}: QAAvatarProps) {
  const { box, icon } = SIZES[size];
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center bg-accent-soft text-accent",
        hero ? "rounded-2xl shadow-[0_2px_8px_0_rgba(4,133,247,0.1)]" : "rounded-full",
        className,
      )}
      style={{ width: box, height: box }}
    >
      <Icon size={icon} strokeWidth={2} aria-hidden />
    </span>
  );
}
