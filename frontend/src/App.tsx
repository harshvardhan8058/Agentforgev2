import { SessionProvider } from "./auth/SessionProvider";
import { AppRouter } from "./routing/AppRouter";

/**
 * Layout shell + router mount.
 *
 * Wraps the application in the `SessionProvider` (token + derived claims) and
 * mounts the `AppRouter` (public `/login`, `/register` + protected routes).
 * Feature views and the premium app shell are layered in by later tasks.
 */
export default function App(): JSX.Element {
  return (
    <SessionProvider>
      <div className="app-shell" data-testid="app-root">
        <AppRouter />
      </div>
    </SessionProvider>
  );
}
