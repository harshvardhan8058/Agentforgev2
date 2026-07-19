/**
 * `ConversationView`: create/select a conversation and view its history
 * (`/conversations`, `/conversations/:id`, Req 15.1, 15.3, 15.4).
 *
 * Two modes, keyed on the `:id` route param:
 *  - **No id** (`/conversations`): a start surface. `POST /conversations`
 *    creates a conversation, the returned `conversation_id` is **retained** in
 *    the shared conversation context (so subsequent runs thread it, Req 15.2),
 *    and the Operator is routed to `/conversations/{id}` (Req 15.1).
 *  - **With id** (`/conversations/:id`): `GET /conversations/{id}` renders the
 *    messages ordered by `position` (Req 15.3); the id is retained as the
 *    active conversation on open; a `404 not_found` presents the conversation
 *    as not found (Req 15.4).
 *
 * Premium UX: skeleton loaders while history loads, an explicit empty state for
 * a conversation with no messages yet, and a uniform `ErrorBanner` for
 * non-404 failures.
 */
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { MessagesSquare, Plus } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { useConversation } from "./ConversationContext";

interface ConversationMessage {
  role: string;
  content: string;
  position: number;
}

interface ConversationHistory {
  conversation_id: string;
  messages?: ConversationMessage[];
}

interface CreateConversationResult {
  conversation_id: string;
}

/** The "start a new conversation" surface (`/conversations`). */
function StartConversation(): JSX.Element {
  const navigate = useNavigate();
  const { setActiveConversation, conversationId } = useConversation();

  const create = useMutation<CreateConversationResult, ClientError, void>({
    mutationFn: () =>
      runRequest<CreateConversationResult>(() =>
        apiClient.POST("/conversations", {}),
      ),
    onSuccess: (data) => {
      setActiveConversation(data.conversation_id);
      navigate(`/conversations/${data.conversation_id}`);
    },
  });

  return (
    <div className="flex flex-col gap-6" data-testid="conversation-view">
      <PageHeader
        eyebrow="Workspace"
        icon={MessagesSquare}
        title="Conversations"
        description="Start a conversation to preserve multi-turn context across agent and multi-agent runs."
      />

      <Card data-testid="conversation-start-card">
        <CardHeader>
          <CardTitle>New conversation</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-text-muted">
            Creating a conversation retains its id so your next run continues the
            same thread.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              data-testid="conversation-start"
              loading={create.isPending}
              onClick={() => create.mutate()}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Start conversation
            </Button>
            {conversationId && (
              <span
                className="text-sm text-text-muted"
                data-testid="active-conversation-id"
              >
                Active: <span className="font-mono">{conversationId}</span>
              </span>
            )}
          </div>
          {create.isError && (
            <div data-testid="conversation-create-error">
              <ErrorBanner error={create.error} />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** The conversation-history surface (`/conversations/:id`). */
function ConversationHistoryPane({ id }: { id: string }): JSX.Element {
  const { orgId } = useSession();
  const { setActiveConversation } = useConversation();

  // Opening a conversation retains it as the active one for subsequent runs.
  useEffect(() => {
    setActiveConversation(id);
  }, [id, setActiveConversation]);

  const history = useQuery<ConversationHistory, ClientError>({
    queryKey: orgScopedKey(orgId, "conversation", id),
    queryFn: () =>
      runRequest<ConversationHistory>(() =>
        apiClient.GET("/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
  });

  if (history.isLoading) {
    return (
      <div className="flex flex-col gap-3" data-testid="conversation-view">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (history.isError) {
    if (history.error.kind === "not_found") {
      return (
        <div data-testid="conversation-view">
          <div data-testid="conversation-not-found">
            <EmptyState
              title="Conversation not found"
              message="This conversation does not exist or is not available in your organization."
              icon={<MessagesSquare className="h-8 w-8" />}
            />
          </div>
        </div>
      );
    }
    return (
      <div data-testid="conversation-view">
        <ErrorBanner
          error={history.error}
          onRetry={() => void history.refetch()}
        />
      </div>
    );
  }

  // Order strictly by position (Req 15.3); never trust server ordering.
  const ordered = [...(history.data?.messages ?? [])].sort(
    (a, b) => a.position - b.position,
  );

  return (
    <div className="flex flex-col gap-6" data-testid="conversation-view">
      <PageHeader
        eyebrow="Workspace"
        icon={MessagesSquare}
        title="Conversation"
        description={
          <span className="font-mono" data-testid="conversation-id">
            {history.data?.conversation_id}
          </span>
        }
      />

      {ordered.length === 0 ? (
        <EmptyState
          title="No messages yet"
          message="Run an agent within this conversation to add messages."
          icon={<MessagesSquare className="h-8 w-8" />}
        />
      ) : (
        <ol className="flex flex-col gap-3" data-testid="conversation-messages">
          {ordered.map((m, i) => (
            <li
              key={`${m.position}-${i}`}
              data-testid={`conversation-message-${m.position}`}
              data-position={m.position}
            >
              <Card>
                <CardContent className="flex flex-col gap-1.5 pt-6">
                  <Badge tone={m.role === "assistant" ? "primary" : "neutral"}>
                    {m.role}
                  </Badge>
                  <p className="whitespace-pre-wrap text-sm text-text">
                    {m.content}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function ConversationView(): JSX.Element {
  const params = useParams<{ id?: string }>();
  const id = params.id;
  if (typeof id === "string" && id.length > 0) {
    return <ConversationHistoryPane id={id} />;
  }
  return <StartConversation />;
}
