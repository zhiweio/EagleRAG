"use client";

import type { KBIconKey, KBTheme } from "@/lib/kb/types";
import { Palette } from "lucide-react";
import { useState } from "react";
import { KBIcon, THEME_STYLES } from "./kb-visuals";

export interface KBPreset {
  theme: KBTheme;
  icon: KBIconKey;
}

/** Design frame 09 Swatch Row: 5 theme-color + icon presets + a "more" palette button. */
export const KB_PRESETS: KBPreset[] = [
  { theme: "blue", icon: "landmark" },
  { theme: "violet", icon: "scroll" },
  { theme: "emerald", icon: "pill" },
  { theme: "amber", icon: "receipt" },
  { theme: "rose", icon: "book" },
];

/** Extra presets revealed after clicking "more". */
export const KB_PRESETS_EXTRA: KBPreset[] = [
  { theme: "indigo", icon: "scale" },
  { theme: "teal", icon: "clipboard" },
  { theme: "sky", icon: "file" },
];

function Swatch({
  preset,
  active,
  onSelect,
}: {
  preset: KBPreset;
  active: boolean;
  onSelect: () => void;
}) {
  const s = THEME_STYLES[preset.theme];
  return (
    <button
      type="button"
      aria-label={`${preset.theme} · ${preset.icon}`}
      aria-pressed={active}
      onClick={onSelect}
      className="flex h-11 w-11 items-center justify-center rounded-lg outline-none transition-transform hover:scale-105"
      style={{
        backgroundColor: s.soft,
        boxShadow: active ? `0 0 0 2px ${s.color}` : undefined,
      }}
    >
      <KBIcon icon={preset.icon} style={{ width: 20, height: 20, color: s.color }} />
    </button>
  );
}

/** Theme-color and icon picker (selects a theme + icon combo at once). */
export function ThemeSwatchPicker({
  theme,
  icon,
  onChange,
}: {
  theme: KBTheme;
  icon: KBIconKey;
  onChange: (theme: KBTheme, icon: KBIconKey) => void;
}) {
  const [showMore, setShowMore] = useState(false);
  const isActive = (p: KBPreset) => p.theme === theme && p.icon === icon;

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {KB_PRESETS.map((p) => (
        <Swatch
          key={p.theme}
          preset={p}
          active={isActive(p)}
          onSelect={() => onChange(p.theme, p.icon)}
        />
      ))}
      {showMore
        ? KB_PRESETS_EXTRA.map((p) => (
            <Swatch
              key={p.theme}
              preset={p}
              active={isActive(p)}
              onSelect={() => onChange(p.theme, p.icon)}
            />
          ))
        : null}
      <button
        type="button"
        aria-label="more themes"
        aria-expanded={showMore}
        onClick={() => setShowMore((v) => !v)}
        className="flex h-11 w-11 items-center justify-center rounded-lg bg-(--surface-muted) text-foreground-tertiary outline-none transition-colors hover:text-foreground-secondary"
      >
        <Palette className="h-[18px] w-[18px]" aria-hidden />
      </button>
    </div>
  );
}
