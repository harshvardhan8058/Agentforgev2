import { Routes, Route } from "react-router-dom";

/**
 * Layout shell + router mount.
 *
 * This is the top-level application shell. Feature routes are added in later
 * tasks (auth, query, documents, agent, multi-agent, analytics, prompts,
 * guardrails, evaluations, conversations); for the scaffold it mounts only a
 * placeholder root so the app renders and the router is wired.
 */
export default function App(): JSX.Element {
  return (
    <div className="app-shell" data-testid="app-root">
      <Routes>
        <Route
          path="*"
          element={
            <main>
              <h1>AgentForge</h1>
              <p>Web console — scaffold ready.</p>
            </main>
          }
        />
      </Routes>
    </div>
  );
}
