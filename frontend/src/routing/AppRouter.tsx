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
 * `UnauthenticatedRedirectBridge` wires the token store's "unauthenticated"
 * hook (fired by the auth middleware on a terminal 401 / refresh failure) to a
 * router navigation to `/login` (Req 3.3, 3.6).
 */
import { useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthenticatedHandler } from "../auth/tokenStore";
import { ProtectedRoute } from "./ProtectedRoute";
import { LoginView } from "../features/auth/LoginView";
import { RegisterView } from "../features/auth/RegisterView";
import { DashboardView } from "../features/dashboard/DashboardView";
import { MembersView } from "../features/orgs/MembersView";
import { ApiKeysView } from "../features/orgs/ApiKeysView";
import { RagQueryView } from "../features/query/RagQueryView";
import { DocumentListView } from "../features/documents/DocumentListView";
import { SingleAgentRunView } from "../features/agent/SingleAgentRunView";
import { MultiAgentRunView } from "../features/multiAgent/MultiAgentRunView";
import { ConversationView } from "../features/conversations/ConversationView";

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
          <Route path="/members" element={<MembersView />} />
          <Route path="/api-keys" element={<ApiKeysView />} />
          <Route path="*" element={<DashboardView />} />
        </Route>
      </Routes>
    </>
  );
}
