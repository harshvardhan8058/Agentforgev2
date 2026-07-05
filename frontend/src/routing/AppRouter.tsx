/**
 * AppRouter: public + protected route table.
 *
 * Public routes (`/login`, `/register`) are reachable with no valid Session;
 * everything else is wrapped by `ProtectedRoute`, which redirects to `/login`
 * when no valid Access_Token is stored (Req 2.5). The feature views for these
 * routes are filled in by later tasks; for now the protected area mounts a
 * placeholder home so the routing/guard behavior is exercisable.
 *
 * `UnauthenticatedRedirectBridge` wires the token store's "unauthenticated"
 * hook (fired by the auth middleware on a terminal 401 / refresh failure) to a
 * router navigation to `/login` (Req 3.3, 3.6).
 */
import { useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthenticatedHandler } from "../auth/tokenStore";
import { ProtectedRoute } from "./ProtectedRoute";

function UnauthenticatedRedirectBridge(): null {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthenticatedHandler(() => navigate("/login", { replace: true }));
    return () => setUnauthenticatedHandler(null);
  }, [navigate]);
  return null;
}

/** Placeholder auth surfaces — replaced by the feature views in later tasks. */
function LoginPlaceholder(): JSX.Element {
  return (
    <main
      data-testid="login-view"
      className="flex min-h-screen flex-col items-center justify-center gap-2 bg-bg p-6 text-center"
    >
      <h1 className="text-3xl font-semibold text-text">AgentForge</h1>
      <p className="text-sm text-text-muted">Sign in to your workspace.</p>
    </main>
  );
}

function RegisterPlaceholder(): JSX.Element {
  return (
    <main
      data-testid="register-view"
      className="flex min-h-screen flex-col items-center justify-center gap-2 bg-bg p-6 text-center"
    >
      <h1 className="text-3xl font-semibold text-text">AgentForge</h1>
      <p className="text-sm text-text-muted">Create your account.</p>
    </main>
  );
}

function HomePlaceholder(): JSX.Element {
  return (
    <main
      data-testid="home-view"
      className="flex min-h-screen flex-col items-center justify-center gap-2 bg-bg p-6 text-center"
    >
      <h1 className="text-3xl font-semibold text-text">AgentForge</h1>
      <p className="text-sm text-text-muted">Web console.</p>
    </main>
  );
}

export function AppRouter(): JSX.Element {
  return (
    <>
      <UnauthenticatedRedirectBridge />
      <Routes>
        <Route path="/login" element={<LoginPlaceholder />} />
        <Route path="/register" element={<RegisterPlaceholder />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<HomePlaceholder />} />
          <Route path="*" element={<HomePlaceholder />} />
        </Route>
      </Routes>
    </>
  );
}
