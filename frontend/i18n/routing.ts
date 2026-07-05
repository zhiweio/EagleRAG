import { createNavigation } from "next-intl/navigation";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["zh", "en"],
  defaultLocale: "en",
  localePrefix: "never",
});

export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);
