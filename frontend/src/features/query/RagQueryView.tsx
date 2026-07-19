/**
 * `RagQueryView`: the grounded RAG query surface (`/query`, Req 7.1–7.6, 4.2).
 *
 * Submits a non-empty query to `POST /query` with an optional `top_k` and
 * renders the returned answer with inline citations, the `provider`, a
 * grounded/ungrounded indicator, and any guardrail `flags`. A
 * `400 guardrail_blocked` withholds the answer and surfaces `details.reason`
 * via the uniform `ErrorBanner`. The submit control is gated behind
 * `run_agents` (Req 4.2) — omitted from the DOM when the Session Role lacks it.
 *
 * `POST /query` returns a full (non-streamed) answer, so this view uses a
 * subtle in-flight skeleton treatment rather than SSE. The answer is rendered
 * through the shared `Markdown` component so inline `[n]` markers become
 * citation links (`extractCitations`, Property 15), and is announced through an
 * `aria-live="polite"` region. An explicit empty state is shown before the
 * first query. Responsive from mobile → ultrawide.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search, Sparkles } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import type { Citation } from "../../api/domain";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorSurface } from "../../components/ErrorSurface";
import { Markdown } from "../../components/markdown/Markdown";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";

/** The shape `POST /query` resolves to (mirrors the generated `QueryResponse`). */
interface QueryResult {
  answer: string;
  grounded: boolean;
  provider: string;
  citations: Citation[];
  flags: string[];
}

const DEFAULT_TOP_K = 5;

export function RagQueryView(): JSX.Element {
  const { role } = useSession();
  const permitted = role !== null && can(role, "run_agents");

  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);

  const submit = useMutation<QueryResult, ClientError, void>({
    mutationFn: async () => {
      const data = await runRequest(() =>
        apiClient.POST("/query", {
          body: { query: query.trim(), top_k: topK },
        }),
      );
      // Normalize the optional collection fields so the view can render safely.
      return {
        answer: data.answer,
        grounded: data.grounded,
        provider: data.provider,
        citations: (data.citations ?? []) as Citation[],
        flags: data.flags ?? [],
      };
    },
  });

  const result = submit.data;
  const trimmed = query.trim();

  return (
    <div className="flex flex-col gap-6" data-testid="query-view">
      <PageHeader
        eyebrow="Retrieval"
        icon={Search}
        title="Query"
        description="Ask a grounded question against your organization's corpus and get a cited answer."
      />

      <Can permission="run_agents">
        <Card data-testid="query-form-card">
          <CardHeader>
            <CardTitle>Ask a question</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3"
              data-testid="query-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (trimmed.length === 0) return;
                submit.mutate();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <label htmlFor="query-input" className="text-sm font-medium text-text">
                  Question
                </label>
                <Input
                  id="query-input"
                  data-testid="query-input"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="What does our onboarding policy say about…"
                />
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="query-top-k" className="text-sm font-medium text-text">
                    Top K
                  </label>
                  <Input
                    id="query-top-k"
                    data-testid="query-top-k"
                    type="number"
                    min={1}
                    className="w-24"
                    value={topK}
                    onChange={(e) => {
                      const next = Number.parseInt(e.target.value, 10);
                      setTopK(Number.isNaN(next) ? DEFAULT_TOP_K : next);
                    }}
                  />
                </div>
                <Button
                  type="submit"
                  data-testid="query-submit"
                  loading={submit.isPending}
                  disabled={trimmed.length === 0}
                >
                  <Search className="h-4 w-4" aria-hidden="true" />
                  Ask
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </Can>

      {!permitted && (
        <EmptyState
          title="Querying unavailable"
          message="Your role does not permit running grounded queries in this organization."
          icon={<Search className="h-8 w-8" />}
        />
      )}

      {/* Guardrail-blocked / error surface — the answer is withheld (Req 7.5).
          A network failure offers a retry that re-submits the preserved input
          (Req 5.6); 429/502 preserve the input for retry (Req 5.4, 6.5). */}
      {submit.isError && (
        <div data-testid="query-error">
          <ErrorSurface error={submit.error} onRetry={() => submit.mutate()} />
        </div>
      )}

      {/* In-flight skeleton treatment while awaiting the full answer. */}
      {submit.isPending && (
        <Card data-testid="query-skeleton">
          <CardContent className="flex flex-col gap-3 pt-6">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </CardContent>
        </Card>
      )}

      {/* Explicit empty state before the first query. */}
      {permitted && !submit.isPending && !submit.isError && !result && (
        <EmptyState
          title="No answer yet"
          message="Ask a question above to see a grounded, cited answer here."
          icon={<Sparkles className="h-8 w-8" />}
        />
      )}

      {/* Success rendering: answer + provider + grounded/ungrounded + flags. */}
      {result && !submit.isPending && (
        <Card data-testid="query-answer-card">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Answer</CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info" data-testid="answer-provider">
                  {result.provider}
                </Badge>
                {result.grounded ? (
                  <Badge tone="success" data-testid="grounded-indicator">
                    Grounded
                  </Badge>
                ) : (
                  <Badge tone="warning" data-testid="ungrounded-indicator">
                    Ungrounded
                  </Badge>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div
              aria-live="polite"
              data-testid="answer-body"
              className="min-w-0"
            >
              <Markdown content={result.answer} citations={result.citations} />
            </div>

            {result.flags.length > 0 && (
              <div className="flex flex-col gap-1.5" data-testid="answer-flags">
                <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                  Guardrail flags
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {result.flags.map((flag) => (
                    <Badge key={flag} tone="warning" data-testid={`flag-${flag}`}>
                      {flag}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {result.citations.length > 0 && (
              <div className="flex flex-col gap-2" data-testid="citation-list">
                <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                  Citations
                </span>
                <ul className="flex flex-col gap-1">
                  {result.citations.map((c, i) => (
                    <li
                      key={`${c.document_id}-${c.chunk_id}-${i}`}
                      id={`citation-${i + 1}`}
                      data-testid={`citation-source-${i + 1}`}
                      className="flex flex-wrap items-center gap-2 text-sm text-text-muted"
                    >
                      <Badge tone="primary">[{i + 1}]</Badge>
                      <span className="font-mono text-xs" data-testid={`citation-doc-${i + 1}`}>
                        {c.document_id}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span className="font-mono text-xs" data-testid={`citation-chunk-${i + 1}`}>
                        {c.chunk_id}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
