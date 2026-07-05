import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

type AppLocale = (typeof routing.locales)[number];

/**
 * Deep-merge a fragment message object into the base messages.
 * Fragment files are namespaced at the top level (e.g. `{ "ingest": {...} }`)
 * so they slot into the merged message tree without clobbering siblings.
 */
function deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): void {
  for (const [key, value] of Object.entries(source)) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const existing = target[key];
      if (existing && typeof existing === "object" && !Array.isArray(value)) {
        deepMerge(existing as Record<string, unknown>, value as Record<string, unknown>);
      } else {
        target[key] = value;
      }
    } else {
      target[key] = value;
    }
  }
}

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale;

  if (!locale || !routing.locales.includes(locale as AppLocale)) {
    locale = routing.defaultLocale;
  }

  // Messages live at `frontend/messages/${locale}.json`; `request.ts` is in
  // `frontend/i18n/`, hence the `../messages/` prefix. Use readFileSync (not
  // dynamic import) so Turbopack doesn't try to bundle the JSON as a module —
  // dynamic `import()` with a variable path hangs SSR in dev mode.
  const baseDir = join(process.cwd(), "messages");
  const messages = JSON.parse(readFileSync(join(baseDir, `${locale}.json`), "utf8")) as Record<
    string,
    unknown
  >;

  // Merge page-level fragment files from `messages/fragments/<name>.<locale>.json`.
  // Each page owns its fragment file; this generic merge lets every page's
  // namespace load without editing the shared `messages/${locale}.json`.
  try {
    const fragmentsDir = join(baseDir, "fragments");
    const suffix = `.${locale}.json`;
    for (const file of readdirSync(fragmentsDir)) {
      if (!file.endsWith(suffix)) continue;
      const fragment = JSON.parse(readFileSync(join(fragmentsDir, file), "utf8")) as Record<
        string,
        unknown
      >;
      deepMerge(messages, fragment);
    }
  } catch {
    // fragments directory missing — nothing to merge.
  }

  return { locale, messages };
});
