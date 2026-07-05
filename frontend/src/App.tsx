import { SessionProvider } from "./auth/SessionProvider";
import { AppRouter } from "./routing/AppRouter";
import { CommandLayer } from "./components/command/CommandLayer";
import { ConversationProvider } from "./features/conversations/ConversationContext";

/**
 * Layout shell + router mount.
 *
 * Wraps the application in the `SessionProvider` (token + derived claims) and
 * mounts the `AppRouter` (public `/login`, `/register` + protected routes). The
 * `CommandLayer` (⌘K palette + `?` shortcuts overlay + global key bindings) is
 * mounted alongside it, inside the session/router/theme context it depends on.
 */
export default function App(): JSX.Element {
  return (
    <SessionProvider>
      <ConversationProvider>
        <div className="app-shell" data-testid="app-root">
          <AppRouter />
          <CommandLayer />
        </div>
      </ConversationProvider>
    </SessionProvider>
  );
}
