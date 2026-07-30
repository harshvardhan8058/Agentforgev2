/**
 * `SingleAgentRunView`: the single-agent run surface (`/agents`, Req 9.1–9.7,
 * 4.2).
 *
 * Two modes, both gated behind `run_agents` (Req 4.2):
 *  - **Streaming** via `POST /agent/stream`, driven by `useSseRun` over the
 *    pure single-agent reducer: `delta` output is rendered incrementally with a
 *    blinking `StreamingCursor` and inline citations; on `completion` the final
 *    answer + citations render; on `error` the error detail renders; a cancel
 *    control is offered while streaming (Req 9.7).
 *  - **Non-streaming** via `POST /agent/run`, showing the answer,
 *    `termination_reason`, and citations (Req 9.4).
 *
 * A completed run exposes its trace via `TraceView`
 * (`GET /agent/runs/{run_id}/trace`, Req 9.5, 9.6).
 */
import type { JSX } from "react";
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Bot, PlayCircle, Radio, StopCircle } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import type { Citation } from "../../api/domain";
import type { SseFrame } from "../../api/sse/parse";
import {
  initialSingleAgentState,
  singleAgentReduce,
  type SingleAgentStreamState,
} from "../../api/sse/singleAgentReducer";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useConversation } from "../conversations/ConversationContext";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Markdown } from "../../components/markdown/Markdown";
import { StreamingCursor } from "../../components/motion/StreamingCursor";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { AGENT_EXAMPLES } from "../../lib/examples";
import { useSseRun } from "./useSseRun";
import { TraceView } from "./TraceView";

interface AgentRunResponse {
  answer: string;
  citations?: Citation[];
  conversation_id: string;
  flags?: string[];
  run_id: string;
  termination_reason: "final-answer" | "iteration-limit-reached";
}

/** Extract the incremental text carried by a `delta` frame's data. */
function deltaText(frame: SseFrame): string {
  const d = frame.data;
  const candidate = d.text ?? d.delta ?? d.token ?? d.content;
  return typeof candidate === "string" ? candidate : "";
}

/** Concatenate the streamed `delta` output accumulated so far, in order. */
function streamedOutput(state: SingleAgentStreamState): string {
  return state.events
    .filter((e) => e.type === "delta")
    .map(deltaText)
    .join("");
}

function CitationList({ citations }: { citations: readonly Citation[] }): JSX.Element | null {
  if (citations.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1" data-testid="agent-citations">
      {citations.map((c, i) => (
        <li
          key={`${c.document_id}-${c.chunk_id}-${i}`}
          id={`citation-${i + 1}`}
          className="flex flex-wrap items-center gap-2 text-sm text-text-muted"
        >
          <Badge tone="primary">[{i + 1}]</Badge>
          <span className="font-mono text-xs">{c.document_id}</span>
          <span aria-hidden="true">·</span>
          <span className="font-mono text-xs">{c.chunk_id}</span>
        </li>
      ))}
    </ul>
  );
}

export function SingleAgentRunView(): JSX.Element {
  const { role } = useSession();
  const { conversationId, setActiveConversation } = useConversation();
  const permitted = role !== null && can(role, "run_agents");

  const [message, setMessage] = useState("");
  const [traceRunId, setTraceRunId] = useState<string | null>(null);

  const reducerConfig = useMemo(
    () => ({ reducer: singleAgentReduce, initialState: initialSingleAgentState }),
    [],
  );
  const stream = useSseRun<SingleAgentStreamState>(reducerConfig);

  const nonStreaming = useMutation<AgentRunResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<AgentRunResponse>(() =>
        apiClient.POST("/agent/run", {
          // Thread the retained conversation id, when active (Req 15.2).
          body: {
            message: message.trim(),
            conversation_id: conversationId ?? undefined,
          },
        }),
      ),
    onSuccess: (data) => {
      setTraceRunId(data.run_id);
      // Retain the run's conversation for subsequent runs (Req 15.1, 15.2).
      if (typeof data.conversation_id === "string") {
        setActiveConversation(data.conversation_id);
      }
    },
  });

  const trimmed = message.trim();
  const streamState = stream.state;
  const streamed = streamedOutput(streamState);
  const runResult = nonStreaming.data;

  function startStreaming(): void {
    if (trimmed.length === 0) return;
    setTraceRunId(null);
    // Thread the retained conversation id, when active (Req 15.2).
    stream.start("/agent/stream", {
      message: trimmed,
      conversation_id: conversationId ?? undefined,
    });
  }

  // Capture the run_id from a streamed completion for the trace view.
  const streamRunId =
    typeof streamState.terminal?.data.run_id === "string"
      ? (streamState.terminal.data.run_id as string)
      : null;
  const effectiveTraceRunId = traceRunId ?? streamRunId;

  // Whether the output column has anything to show. Covers a live or finished
  // stream, a non-streaming result, either failure path, and a resolved trace.
  const hasOutput =
    stream.isStreaming ||
    streamState.events.length > 0 ||
    streamState.closed ||
    Boolean(stream.error) ||
    nonStreaming.isError ||
    Boolean(runResult) ||
    Boolean(effectiveTraceRunId);

  return (
    <div className="flex flex-col gap-6" data-testid="agent-view">
      <PageHeader
        eyebrow="Agents"
        icon={Bot}
        title="Agent Runs"
        description="Run a single agent and watch its reasoning stream live, or run it to completion."
      />

      {!permitted && (
        <EmptyState
          title="Agent runs unavailable"
          message="Your role does not permit running agents in this organization."
          icon={<Bot className="h-8 w-8" />}
        />
      )}

      {/*
        A run page is a form plus the output it produces. Stacked vertically, the
        form was one short card at the top of an otherwise empty viewport, and
        once a run finished the form scrolled away — so re-running with a tweaked
        message meant scrolling back up. Side by side on a wide screen, the form
        stays put while the output fills the space next to it.
      */}
      {permitted && (
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4 lg:sticky lg:top-4">
      <Can permission="run_agents">
        <Card data-testid="agent-form-card">
          <CardHeader>
            <CardTitle>New run</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="agent-message" className="text-sm font-medium text-text">
                Message
              </label>
              <Input
                id="agent-message"
                data-testid="agent-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Summarize the latest incident report…"
              />
              <ExampleChips
                testId="agent-examples"
                examples={AGENT_EXAMPLES}
                onPick={setMessage}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                data-testid="agent-run-stream"
                disabled={trimmed.length === 0 || stream.isStreaming}
                onClick={startStreaming}
              >
                <Radio className="h-4 w-4" aria-hidden="true" />
                Run (streaming)
              </Button>
              <Button
                type="button"
                variant="secondary"
                data-testid="agent-run"
                loading={nonStreaming.isPending}
                disabled={trimmed.length === 0}
                onClick={() => nonStreaming.mutate()}
              >
                <PlayCircle className="h-4 w-4" aria-hidden="true" />
                Run
              </Button>
              {stream.isStreaming && (
                <Button
                  type="button"
                  variant="danger"
                  data-testid="agent-cancel"
                  onClick={() => stream.cancel()}
                >
                  <StopCircle className="h-4 w-4" aria-hidden="true" />
                  Cancel
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </Can>
      </div>

      <div className="flex min-w-0 flex-col gap-4" data-testid="agent-output">
      {/* Nothing has been run yet: explain the two modes rather than leaving the
          column blank, since the difference between them is not obvious from the
          button labels alone. */}
      {!hasOutput && (
        <Card data-testid="agent-idle">
          <CardHeader>
            <CardTitle className="text-base">No run yet</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-text-muted">
            <p className="leading-relaxed">
              Pick an example or write a message, then choose how to run it.
            </p>
            <div className="flex flex-col gap-2">
              <p className="flex items-start gap-2">
                <Radio
                  className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <span>
                  <span className="font-medium text-text">Run (streaming)</span> —
                  each reasoning step and tool call appears as it happens, and the
                  run can be cancelled part-way.
                </span>
              </p>
              <p className="flex items-start gap-2">
                <PlayCircle
                  className="mt-0.5 h-4 w-4 shrink-0 text-text-subtle"
                  aria-hidden="true"
                />
                <span>
                  <span className="font-medium text-text">Run</span> — waits for
                  the agent to finish and returns the final answer with its
                  citations.
                </span>
              </p>
            </div>
            <p className="leading-relaxed">
              Either way the answer is grounded in your documents. Load the sample
              corpus from the Documents page if yours is empty.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Streaming run output. */}
      {(stream.isStreaming || streamState.events.length > 0 || streamState.closed) && (
        <Card data-testid="stream-card">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Streaming run</CardTitle>
              {stream.isStreaming && (
                <Badge tone="info" data-testid="streaming-indicator">
                  Streaming…
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {/* Live incremental output with a streaming cursor. */}
            {!streamState.closed && (
              <div
                aria-live="polite"
                data-testid="stream-output"
                className="min-w-0"
              >
                <Markdown content={streamed} />
                {stream.isStreaming && <StreamingCursor />}
              </div>
            )}

            {/* Terminal: completion → final answer + citations. */}
            {streamState.closed && streamState.terminal?.type === "completion" && (
              <div className="flex flex-col gap-3" data-testid="stream-answer">
                <Markdown
                  content={streamState.answer ?? ""}
                  citations={streamState.citations}
                />
                {streamState.terminationReason && (
                  <Badge tone="neutral" data-testid="stream-termination-reason">
                    {streamState.terminationReason}
                  </Badge>
                )}
                <CitationList citations={streamState.citations} />
              </div>
            )}

            {/* Terminal: error → error detail. */}
            {streamState.closed && streamState.terminal?.type === "error" && (
              <p className="text-sm text-danger" data-testid="stream-error">
                {streamState.errorMessage}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Transport/open error for the stream. */}
      {stream.error && (
        <div data-testid="stream-transport-error">
          <ErrorBanner error={stream.error} />
        </div>
      )}

      {/* Non-streaming run result. */}
      {nonStreaming.isError && (
        <div data-testid="run-error">
          <ErrorBanner error={nonStreaming.error} />
        </div>
      )}
      {runResult && (
        <Card data-testid="run-result-card">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Run result</CardTitle>
              <Badge tone="neutral" data-testid="run-termination-reason">
                {runResult.termination_reason}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div data-testid="run-answer" className="min-w-0">
              <Markdown
                content={runResult.answer}
                citations={runResult.citations ?? []}
              />
            </div>
            <CitationList citations={runResult.citations ?? []} />
          </CardContent>
        </Card>
      )}

      {/* Trace for a completed run. */}
      {effectiveTraceRunId && (
        <Card data-testid="trace-card">
          <CardHeader>
            <CardTitle>Run trace</CardTitle>
          </CardHeader>
          <CardContent>
            <TraceView runId={effectiveTraceRunId} />
          </CardContent>
        </Card>
      )}
      </div>
      </div>
      )}
    </div>
  );
}
