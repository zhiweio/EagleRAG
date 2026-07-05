import { createNavigation } from "next-intl/navigation";
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["zh", "en"],
  defaultLocale: "zh",
  // never：所有 locale 均无 URL 前缀。中文访问 /ingest，英文也访问 /ingest，
  // 语言由 cookie / Accept-Locale 协商决定。Next.js 16.2+ 已修复 Turbopack 下
  // 根路径 [locale] 段不填充导致 404 的问题，never 模式可正常工作。
  localePrefix: "never",
});

export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);
