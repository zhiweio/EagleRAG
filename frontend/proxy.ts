import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

// Next.js 16 renamed `middleware.ts` to `proxy.ts`. next-intl's `createMiddleware`
// still produces the request handler used here.
export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for `/api`, `/_next`, `/_vercel` and static files
  // (pathnames containing a dot, e.g. `favicon.ico`).
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
