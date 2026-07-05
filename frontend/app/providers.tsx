"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

/**
 * HeroUI v3 is providerless: theming is done with CSS variables (see
 * `app/globals.css`) and there is no `HeroUIProvider` / `theme` prop anymore.
 *
 * This wrapper is kept as an integration seam so future global providers
 * (toast region, router `navigate` config, etc.) can be added in one place.
 * It also mounts React Query's QueryClientProvider to unify client-side data fetching cache.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
