/**
 * `RecentConversations`: the org's existing conversation threads.
 *
 * The Conversations page was a single "Start conversation" button. Creating a thread
 * returned its id once, and there was no way to enumerate threads afterwards — so a
 * conversation became unreachable the moment its id left the screen, and the page
 * displaying "Conversations" could not show a single one. `GET /conversations` was added
 * for exactly this.
 *
 * Each row leads with the first message rather than the id, because a UUID says nothing
 * about which thread it is.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { MessagesSquare } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatWhen } from "../../lib/formatWhen";

interface ConversationSummary {
  conversation_id: string;
  created_at: string;
  message_count: number;
  preview?: string | null;
}

export function RecentConversations(): JSX.Element {
  const { orgId } = useSession();

  const conversations = useQuery<ConversationSummary[], ClientError>({
    queryKey: orgScopedKey(orgId, "conversations"),
    queryFn: () =>
      runRequest<ConversationSummary[]>(() => apiClient.GET("/conversations")),
  });

  const rows = conversations.data ?? [];

  return (
    <Card data-testid="recent-conversations-card">
      <CardHeader>
        <CardTitle className="text-base">Your conversations</CardTitle>
      </CardHeader>
      <CardContent>
        {conversations.isLoading && (
          <div className="flex flex-col gap-2" data-testid="conversations-skeleton">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}

        {conversations.isError && (
          <ErrorBanner
            error={conversations.error}
            onRetry={() => void conversations.refetch()}
          />
        )}

        {conversations.data && rows.length === 0 && (
          <div data-testid="conversations-empty">
            <EmptyState
              title="No conversations yet"
              message="Start one above; every agent run inside it shares the same thread of context."
              icon={<MessagesSquare className="h-8 w-8" />}
            />
          </div>
        )}

        {rows.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="conversations-list">
            {rows.map((row) => (
              <li key={row.conversation_id}>
                <Link
                  to={`/conversations/${row.conversation_id}`}
                  data-testid={`conversation-row-${row.conversation_id}`}
                  className="af-interactive flex flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                >
                  <span className="flex flex-wrap items-center justify-between gap-2">
                    {/* The first message, not the id: that is what identifies a
                        thread to a person. */}
                    <span className="truncate text-sm font-medium text-text">
                      {row.preview ?? "Empty conversation"}
                    </span>
                    <Badge tone="neutral">
                      {row.message_count} message{row.message_count === 1 ? "" : "s"}
                    </Badge>
                  </span>
                  <span className="text-xs text-text-subtle">
                    {formatWhen(row.created_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
