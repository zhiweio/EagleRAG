import { createNavigation } from "next-intl/navigation";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["zh", "en"],
  defaultLocale: "zh",
  // always: localePrefix "never" internal rewrites under Next.js 16 proxy.ts + Turbopack
  // do not populate app/[locale] (root and nested paths 404 or 307-loop); use explicit prefixes.
  localePrefix: "always",
});

export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);
