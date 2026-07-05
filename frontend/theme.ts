/**
 * Eagle-RAG design tokens (Pencil light-theme).
 *
 * HeroUI v3 theming is CSS-variable based: there is no `createTheme`/
 * `extendTheme` and `HeroUIProvider` no longer accepts a `theme` prop. The
 * tokens below are applied as CSS custom properties in `app/globals.css`
 * (overriding HeroUI's default `:root` / `[data-theme="light"]` variables).
 *
 * This module exposes the same values as a typed object so they can be reused
 * in non-CSS contexts (charts, canvas, inline styles, etc.).
 */

export const designTokens = {
  brand: "Eagle-RAG",
  colors: {
    accent: "#0485F7",
    accentHover: "#3592F9",
    accentSoft: "#0485F726",
    accentSoftForeground: "#0485F7",
    accentSoftHover: "#0485F733",
    accentForeground: "#FCFCFC",

    background: "#F5F5F5",
    backgroundSecondary: "#EBEBEB",
    backgroundTertiary: "#E1E1E1",
    backgroundInverse: "#18181B",

    foreground: "#18181B",
    foregroundMuted: "#71717A",
    foregroundSecondary: "#71717A",
    foregroundTertiary: "#A1A1AA",
    foregroundInverse: "#FCFCFC",
    foregroundOverlay: "#18181B",
    foregroundLink: "#18181B",
    foregroundSegment: "#18181B",

    surface: "#FFFFFF",
    surfaceSecondary: "transparent",
    surfaceTransparent: "transparent",
    surfaceMuted: "#EFEFF0",
    bubble: "#EBEBEC",

    border: "#DEDEE0",
    default: "#EBEBEC",
    defaultForeground: "#18181B",
    defaultHover: "#E1E1E2",

    success: "#17C964",
    successForeground: "#FCFCFC",

    warning: "#F5A524",
    warningForeground: "#18181B",

    danger: "#FF383C",
    dangerHover: "#FF5551",
    dangerSoft: "#FF383C26",
    dangerSoftForeground: "#FF383C",
    dangerSoftHover: "#FF555133",
    dangerForeground: "#FCFCFC",

    focusRing: "#0485F7",
    backdrop: "#00000080",

    fieldBackground: "#FFFFFF",
    fieldBackgroundFocus: "#FFFFFF",
    fieldBackgroundHover: "#F9F9F9EB",
    fieldForeground: "#18181B",
    fieldPlaceholder: "#71717A",
    fieldBorderFocus: "#ABABAF",
    fieldBorderHover: "transparent",
    fieldShadow: "#0000000A",
    fieldShadow2: "#0000000F",
  },
  radius: {
    xs: 2,
    sm: 4,
    md: 6,
    lg: 8,
    xl: 12,
    "2xl": 16,
    "3xl": 24,
    "4xl": 32,
    full: 9999,
  },
  fonts: {
    sans: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
    mono: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
  },
  spacing: [
    0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 56, 64, 80, 96, 112,
    128, 144, 160, 176, 192, 208, 224, 240, 256, 288, 320, 384,
  ],
  disabledOpacity: 50,
  borderWidth: 1,
  borderWidthControl: 0,
} as const;

/**
 * Kept for compatibility with the spec's `Providers` wiring.
 * HeroUI v3 consumes these values through CSS variables, not via this object.
 */
export const theme = designTokens;

export type DesignTokens = typeof designTokens;
