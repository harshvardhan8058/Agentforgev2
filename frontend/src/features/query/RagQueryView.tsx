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
import type { JSX } from "react";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, FilePlus2, FileText, Search, Sparkles } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import type { Citation } from "../../api/domain";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorSurface } from "../../components/ErrorSurface";
import { FallbackNotice } from "../../components/FallbackNotice";
import {
  GeneralKnowledgeNotice,
  isGeneralKnowledgeAnswer,
} from "../../components/GeneralKnowledgeNotice";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { Skeleton } from "../../components/ui/Skeleton";
import { UploadControl } from "../documents/UploadControl";
import { StreamingAnswer } from "./StreamingAnswer";
import { cn } from "../../lib/cn";

/** One-click starter questions for an empty corpus/first-time Operator. */
const QUERY_EXAMPLES: readonly string[] = [
  "Summarize the key points of this document",
  "What are the important dates mentioned?",
  "What does the document say about compensation?",
];

/** The shape `POST /query` resolves to (mirrors the generated `QueryResponse`). */
interface QueryResult {
  answer: string;
  grounded: boolean;
  provider: string;
  citations: Citation[];
  flags: string[];
}

/** Minimal document shape used to resolve citation filenames. */
interface DocumentSummary {
  document_id: string;
  filename: string;
}

const DEFAULT_TOP_K = 5;

/**
 * The inclusive range `POST /query` accepts for `top_k`. Mirrored here so the
 * control cannot emit a value the API would reject with a 422.
 */
const TOP_K_MIN = 1;
const TOP_K_MAX = 10;

/** Coerce arbitrary input into a valid `top_k`, falling back to the default. */
function clampTopK(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return DEFAULT_TOP_K;
  return Math.min(TOP_K_MAX, Math.max(TOP_K_MIN, parsed));
}

export function RagQueryView(): JSX.Element {
  const { role, orgId } = useSession();
  const permitted = role !== null && can(role, "run_agents");

  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [showUpload, setShowUpload] = useState(false);

  // Resolve citation document ids to human-readable filenames (best-effort).
  const documents = useQuery<DocumentSummary[], ClientError>({
    enabled: permitted,
    queryKey: orgScopedKey(orgId, "documents"),
    queryFn: () => runRequest(() => apiClient.GET("/documents")),
    retry: false,
    staleTime: 30_000,
  });

  const filenameById = useMemo(() => {
    const map = new Map<string, string>();
    // Defensive: the endpoint (or a mock) may return a non-array; never iterate
    // a non-iterable, which would throw during render.
    const docs = Array.isArray(documents.data) ? documents.data : [];
    for (const doc of docs) map.set(doc.document_id, doc.filename);
    return map;
  }, [documents.data]);

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
                  // Focusing the primary input on this single-purpose task page
                  // is an expected, modern affordance (matches the auth pages).
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="What does our onboarding policy say about…"
                />
                <ExampleChips
                  testId="query-examples"
                  examples={QUERY_EXAMPLES}
                  onPick={setQuery}
                />
              </div>
              <div className="flex flex-wrap items-end gap-4">
                {/* Retrieval breadth. Presented in plain language rather than as
                    "Top K", and constrained to the range the API accepts so an
                    out-of-range value can never produce a 422. */}
                <div className="flex min-w-[15rem] flex-1 flex-col gap-1.5 sm:max-w-xs">
                  <div className="flex items-baseline justify-between gap-2">
                    <label htmlFor="query-top-k" className="text-sm font-medium text-text">
                      Sources to search
                    </label>
                    <span
                      className="text-sm font-medium tabular-nums text-text-muted"
                      data-testid="query-top-k-value"
                    >
                      {topK} of {TOP_K_MAX}
                    </span>
                  </div>
                  <input
                    id="query-top-k"
                    data-testid="query-top-k"
                    type="range"
                    min={TOP_K_MIN}
                    max={TOP_K_MAX}
                    step={1}
                    value={topK}
                    aria-describedby="query-top-k-hint"
                    onChange={(e) => setTopK(clampTopK(e.target.value))}
                    className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-bg-subtle accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                  />
                  <p id="query-top-k-hint" className="text-xs text-text-muted">
                    How many excerpts from your documents are used as context. Fewer
                    keeps the answer tightly focused; more covers longer documents.
                  </p>
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

            {/* Inline corpus ingestion: add a document without leaving the
                query flow. Collapsed by default and gated behind the same
                `ingest_documents` permission as the Documents page. */}
            <Can permission="ingest_documents">
              <div className="mt-4 border-t border-border pt-4">
                <button
                  type="button"
                  onClick={() => setShowUpload((v) => !v)}
                  aria-expanded={showUpload}
                  aria-controls="query-upload-panel"
                  data-testid="query-upload-toggle"
                  className="inline-flex items-center gap-2 rounded-md text-sm font-medium text-text-muted transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                >
                  <FilePlus2 className="h-4 w-4" aria-hidden="true" />
                  Add a document to your corpus
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 transition-transform duration-base",
                      showUpload && "rotate-180",
                    )}
                    aria-hidden="true"
                  />
                </button>
                {showUpload && (
                  <div id="query-upload-panel" className="mt-3" data-testid="query-upload-panel">
                    <UploadControl />
                    <p className="mt-2 text-xs text-text-subtle">
                      Newly ingested documents are searchable immediately — ask your
                      question above once ingestion completes.
                    </p>
                  </div>
                )}
              </div>
            </Can>
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
            {result.provider === "fallback" && <FallbackNotice />}
            {isGeneralKnowledgeAnswer(result.grounded, result.answer) && (
              <GeneralKnowledgeNotice />
            )}
            <div
              aria-live="polite"
              data-testid="answer-body"
              className="min-w-0"
            >
              <StreamingAnswer text={result.answer} citations={result.citations} />
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
                  {result.citations.map((c, i) => {
                    const filename = filenameById.get(c.document_id);
                    return (
                      <li
                        key={`${c.document_id}-${c.chunk_id}-${i}`}
                        id={`citation-${i + 1}`}
                        data-testid={`citation-source-${i + 1}`}
                        className="flex flex-wrap items-center gap-2 text-sm text-text-muted"
                      >
                        <Badge tone="primary">[{i + 1}]</Badge>
                        <FileText
                          className="h-3.5 w-3.5 shrink-0 text-text-subtle"
                          aria-hidden="true"
                        />
                        {/* Prefer the human-readable filename; the raw document
                            id is preserved in the title for reference. */}
                        <span
                          className={cn(
                            "text-xs",
                            filename ? "font-medium text-text" : "font-mono",
                          )}
                          data-testid={`citation-doc-${i + 1}`}
                          title={c.document_id}
                        >
                          {filename ?? c.document_id}
                        </span>
                        <span aria-hidden="true">·</span>
                        <span
                          className="font-mono text-xs"
                          data-testid={`citation-chunk-${i + 1}`}
                        >
                          {c.chunk_id}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
