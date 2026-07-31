/**
 * AppRouter: public + protected route table.
 *
 * Public routes (`/login`, `/register`) are reachable with no valid Session;
 * everything else is wrapped by `ProtectedRoute`, which redirects to `/login`
 * when no valid Access_Token is stored (Req 2.5). The auth feature views
 * (`LoginView`/`RegisterView`) back the public routes; the protected area
 * mounts the dashboard plus the org member/team and API-key management surfaces
 * (each view RBAC-gates its own controls).
 *
 * Performance: the auth views and the dashboard are eagerly imported (they are
 * the first paint targets), while every heavier feature route is **code-split**
 * via `React.lazy`, so its chunk (and its transitive deps — markdown/highlight,
 * charts, editor, etc.) loads only when the Operator navigates to it. A
 * `Suspense` boundary inside `ProtectedRoute` renders a layout-matching
 * fallback while a route chunk is fetched.
 *
 * `UnauthenticatedRedirectBridge` wires the token store's "unauthenticated"
 * hook (fired by the auth middleware on a terminal 401 / refresh failure) to a
 * router navigation to `/login` (Req 3.3, 3.6).
 */
import type { JSX } from "react";
import { lazy, useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router";

import { setUnauthenticatedHandler } from "../auth/tokenStore";
import { ProtectedRoute } from "./ProtectedRoute";
import { LoginView } from "../features/auth/LoginView";
import { RegisterView } from "../features/auth/RegisterView";
import { DashboardView } from "../features/dashboard/DashboardView";

// Heavier feature routes are code-split; their chunks load on navigation only.
const RagQueryView = lazy(() =>
  import("../features/query/RagQueryView").then((m) => ({ default: m.RagQueryView })),
);
const DocumentListView = lazy(() =>
  import("../features/documents/DocumentListView").then((m) => ({
    default: m.DocumentListView,
  })),
);
const SingleAgentRunView = lazy(() =>
  import("../features/agent/SingleAgentRunView").then((m) => ({
    default: m.SingleAgentRunView,
  })),
);
const MultiAgentRunView = lazy(() =>
  import("../features/multiAgent/MultiAgentRunView").then((m) => ({
    default: m.MultiAgentRunView,
  })),
);
const ConversationView = lazy(() =>
  import("../features/conversations/ConversationView").then((m) => ({
    default: m.ConversationView,
  })),
);
const UsageDashboardView = lazy(() =>
  import("../features/analytics/UsageDashboardView").then((m) => ({
    default: m.UsageDashboardView,
  })),
);
const PromptRegistryView = lazy(() =>
  import("../features/prompts/PromptRegistryView").then((m) => ({
    default: m.PromptRegistryView,
  })),
);
const GuardrailsView = lazy(() =>
  import("../features/guardrails/GuardrailsView").then((m) => ({
    default: m.GuardrailsView,
  })),
);
const EvaluationsView = lazy(() =>
  import("../features/evaluations/EvaluationsView").then((m) => ({
    default: m.EvaluationsView,
  })),
);
const MembersView = lazy(() =>
  import("../features/orgs/MembersView").then((m) => ({ default: m.MembersView })),
);
const ApiKeysView = lazy(() =>
  import("../features/orgs/ApiKeysView").then((m) => ({ default: m.ApiKeysView })),
);
const IntegrationsView = lazy(() =>
  import("../features/integrations/IntegrationsView").then((m) => ({
    default: m.IntegrationsView,
  })),
);
const NotFoundView = lazy(() =>
  import("../features/misc/NotFoundView").then((m) => ({ default: m.NotFoundView })),
);

function UnauthenticatedRedirectBridge(): null {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthenticatedHandler(() => navigate("/login", { replace: true }));
    return () => setUnauthenticatedHandler(null);
  }, [navigate]);
  return null;
}

export function AppRouter(): JSX.Element {
  return (
    <>
      <UnauthenticatedRedirectBridge />
      <Routes>
        <Route path="/login" element={<LoginView />} />
        <Route path="/register" element={<RegisterView />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<DashboardView />} />
          <Route path="/query" element={<RagQueryView />} />
          <Route path="/documents" element={<DocumentListView />} />
          <Route path="/agents" element={<SingleAgentRunView />} />
          <Route path="/multi-agent" element={<MultiAgentRunView />} />
          <Route path="/conversations" element={<ConversationView />} />
          <Route path="/conversations/:id" element={<ConversationView />} />
          <Route path="/analytics" element={<UsageDashboardView />} />
          <Route path="/prompts" element={<PromptRegistryView />} />
          <Route path="/guardrails" element={<GuardrailsView />} />
          <Route path="/evaluations" element={<EvaluationsView />} />
          <Route path="/integrations" element={<IntegrationsView />} />
          <Route path="/members" element={<MembersView />} />
          <Route path="/api-keys" element={<ApiKeysView />} />
          <Route path="*" element={<NotFoundView />} />
        </Route>
      </Routes>
    </>
  );
}
