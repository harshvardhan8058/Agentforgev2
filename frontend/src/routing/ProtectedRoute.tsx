/**
 * ProtectedRoute: guards authenticated routes.
 *
 * Whenever no valid Access_Token is stored — absent, expired, or malformed —
 * it redirects the Operator to `/login`, restricting them to the
 * unauthenticated views (Req 2.5, 3.2). Otherwise it renders the nested route
 * via `<Outlet />`.
 */
import { Suspense } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { useSession } from "../auth/useSession";
import { AppShell } from "../components/shell/AppShell";
import { RouteTransition } from "./RouteTransition";
import { PageFallback } from "./PageFallback";

export function ProtectedRoute(): JSX.Element {
  const { isAuthenticated } = useSession();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return (
    <AppShell>
      <RouteTransition>
        <Suspense fallback={<PageFallback />}>
          <Outlet />
        </Suspense>
      </RouteTransition>
    </AppShell>
  );
}
