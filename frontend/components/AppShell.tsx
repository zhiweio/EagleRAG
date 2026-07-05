"use client";

import { AppBar } from "@/components/AppBar";
import { GlobalSearchModal } from "@/components/GlobalSearchModal";
import { useUIStore } from "@/lib/stores/uiStore";
import type { ReactNode } from "react";
import { useEffect } from "react";

/**
 * AppShell — global chrome: sticky AppBar, Cmd/Ctrl+K document search, and page
 * content. Mounted once from the locale layout so individual routes do not
 * duplicate the header.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const setGlobalSearchOpen = useUIStore((s) => s.setGlobalSearchOpen);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setGlobalSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setGlobalSearchOpen]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AppBar />
      <GlobalSearchModal />
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
