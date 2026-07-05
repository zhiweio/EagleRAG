/**
 * Minimal className joiner. Filters out falsy values and joins with spaces.
 * Kept dependency-free (no clsx / tailwind-merge) — order-last class wins per
 * normal CSS cascade, which is sufficient for our token-based utilities.
 */
export type ClassValue = string | number | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
