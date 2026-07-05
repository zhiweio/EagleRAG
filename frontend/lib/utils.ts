import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names with Tailwind conflict resolution.
 *
 * Standard shadcn/ui helper: `clsx` handles conditional classes and
 * `tailwind-merge` de-duplicates conflicting Tailwind utilities (e.g. keeps the
 * last of `p-2 p-4`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
