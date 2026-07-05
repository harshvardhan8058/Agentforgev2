/**
 * Conversation context (Req 15.1, 15.2).
 *
 * A tiny shared provider that **retains** the active `conversation_id` created
 * via `POST /conversations`, so subsequent single-agent (`features/agent`) and
 * multi-agent (`features/multiAgent`) run submissions can thread it into their
 * request bodies (Req 15.2) and preserve multi-turn context across runs.
 *
 * The context carries a sane default (no active conversation, no-op setters) so
 * views that consume `useConversation` still work when rendered outside a
 * provider (e.g. isolated component tests); mounting `ConversationProvider`
 * above the router in `App` gives the whole authenticated app a single shared
 * retained id.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** The retained-conversation API exposed to run views. */
export interface ConversationApi {
  /** The retained active `conversation_id`, or `null` when none is active. */
  conversationId: string | null;
  /** Retain `id` as the active conversation for subsequent runs (Req 15.1). */
  setActiveConversation(id: string): void;
  /** Clear the active conversation. */
  clearConversation(): void;
}

const DEFAULT: ConversationApi = {
  conversationId: null,
  setActiveConversation: () => {},
  clearConversation: () => {},
};

const ConversationContext = createContext<ConversationApi>(DEFAULT);

export function ConversationProvider({
  children,
  initialConversationId = null,
}: {
  children: ReactNode;
  /** Seed an active conversation (used by tests / deep links). */
  initialConversationId?: string | null;
}): JSX.Element {
  const [conversationId, setConversationId] = useState<string | null>(
    initialConversationId,
  );

  const setActiveConversation = useCallback((id: string) => {
    setConversationId(id);
  }, []);
  const clearConversation = useCallback(() => {
    setConversationId(null);
  }, []);

  const value = useMemo<ConversationApi>(
    () => ({ conversationId, setActiveConversation, clearConversation }),
    [conversationId, setActiveConversation, clearConversation],
  );

  return (
    <ConversationContext.Provider value={value}>
      {children}
    </ConversationContext.Provider>
  );
}

/** Access the retained conversation context (never throws; has a default). */
export function useConversation(): ConversationApi {
  return useContext(ConversationContext);
}
