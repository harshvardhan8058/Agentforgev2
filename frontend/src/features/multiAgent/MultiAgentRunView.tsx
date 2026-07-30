/**
 * `MultiAgentRunView`: the multi-agent run + approval surface
 * (`/multi-agent`, Req 10.1–10.8, 4.2).
 *
 * Flow (all run/approval controls gated behind `run_agents`, Req 4.2):
 *  1. **Start** — `POST /multi-agent/runs` with `{ task, conversation_id? }`
 *     shows the returned `run_id`, `conversation_id`, and `status` (Req 10.1).
 *     The returned `conversation_id` is retained in the shared conversation
 *     context so subsequent runs thread it (Req 15.2).
 *  2. **Stream** — `POST /multi-agent/runs/{id}/stream` opened via `useSseRun`
 *     over the pure multi-agent reducer: events are attributed to their
 *     `role_id` and ordered by `sequence` (Req 10.2), visualized live by the
 *     `WorkflowVisualizer`. On `approval_required` (non-terminal) the
 *     `ApprovalPanel` is rendered (Req 10.3, 10.4); on `completion` the final
 *     output + citations render (Req 10.5).
 *  3. **Result** — `GET /multi-agent/runs/{id}` shows status, termination
 *     reason, final output, and the role-attributed trace (Req 10.6); `404` →
 *     not found (Req 10.7); a `409` on approval refreshes this result (Req 10.8).
 *
 * Premium UX: an animated Planner → Researcher → Writer → Critic visualization
 * with per-role accent tokens, an elevated non-terminal approval panel, an
 * ordered event log, and rich empty/streaming/success/error states. Motion is
 * reduced-motion aware and instant under test.
 */
import type { JSX } from "react";
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ListTree, PlayCircle, Radio, Sparkles, StopCircle } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import type { SseFrame } from "../../api/sse/parse";
import {
  initialMultiAgentState,
  multiAgentReduce,
  type MultiAgentStreamState,
} from "../../api/sse/multiAgentReducer";
import { can } from "../../auth/rbac";
import { stripDecisionEnvelope } from "../../lib/agentText";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Markdown } from "../../components/markdown/Markdown";
import { StreamingCursor } from "../../components/motion/StreamingCursor";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { CopyableId } from "../../components/ui/CopyableId";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { MULTI_AGENT_EXAMPLES } from "../../lib/examples";
import { useSseRun } from "../agent/useSseRun";
import { useConversation } from "../conversations/ConversationContext";
import { ApprovalPanel } from "./ApprovalPanel";
import { MultiAgentRunResult } from "./MultiAgentRunResult";
import { WorkflowVisualizer } from "./WorkflowVisualizer";

interface StartRunResponse {
  run_id: string;
  conversation_id: string;
  status: "running" | "awaiting_approval" | "terminated";
  flags?: string[];
}

/** The role attributed to an ordered event, if any. */
function roleOf(frame: SseFrame): string | null {
  return typeof frame.data.role_id === "string" ? frame.data.role_id : null;
}

/**
 * A short summary of an event for the ordered log.
 *
 * Event text originates from the model, so it passes through
 * `stripDecisionEnvelope` for the same reason `Markdown` does: the log is plain
 * text, not markdown, so it would otherwise be the one surface where a leaked
 * decision envelope could still be displayed verbatim. The transform is
 * identity for anything that is not envelope-shaped.
 */
function summarize(frame: SseFrame): string {
  const d = frame.data;
  if (typeof d.content === "string" && d.content.length > 0) {
    return stripDecisionEnvelope(d.content);
  }
  if (typeof d.comments === "string" && d.comments.length > 0) {
    return stripDecisionEnvelope(d.comments);
  }
  if (typeof d.checkpoint === "string" && d.checkpoint.length > 0) return d.checkpoint;
  if (Array.isArray(d.steps) && d.steps.length > 0) {
    return stripDecisionEnvelope(
      d.steps.filter((s) => typeof s === "string").join(", "),
    );
  }
  return "";
}

export function MultiAgentRunView(): JSX.Element {
  const { role } = useSession();
  const { conversationId, setActiveConversation } = useConversation();
  const permitted = role !== null && can(role, "run_agents");

  const [task, setTask] = useState("");
  const [run, setRun] = useState<StartRunResponse | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [resultRefresh, setResultRefresh] = useState(0);

  const reducerConfig = useMemo(
    () => ({ reducer: multiAgentReduce, initialState: initialMultiAgentState }),
    [],
  );
  const stream = useSseRun<MultiAgentStreamState>(reducerConfig);
  const streamState = stream.state;

  const start = useMutation<StartRunResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<StartRunResponse>(() =>
        apiClient.POST("/multi-agent/runs", {
          body: {
            task: task.trim(),
            // Thread the retained conversation id, when active (Req 15.2).
            conversation_id: conversationId ?? undefined,
          },
        }),
      ),
    onSuccess: (data) => {
      setRun(data);
      setShowResult(false);
      // Retain the returned conversation id for subsequent runs (Req 15.2).
      setActiveConversation(data.conversation_id);
    },
  });

  const trimmed = task.trim();

  function openStream(): void {
    if (run === null) return;
    setShowResult(false);
    stream.start(`/multi-agent/runs/${run.run_id}/stream`, {});
  }

  function refreshResult(): void {
    setShowResult(true);
    setResultRefresh((n) => n + 1);
  }

  const hasStreamActivity =
    stream.isStreaming || streamState.events.length > 0 || streamState.closed;

  return (
    <div className="flex flex-col gap-6" data-testid="multi-agent-view">
      <PageHeader
        eyebrow="Agents"
        icon={Sparkles}
        title="Multi-Agent Runs"
        description="Launch a Planner → Researcher → Writer → Critic collaboration, watch each role stream, and act on approval checkpoints."
      />

      {!permitted && (
        <EmptyState
          title="Multi-agent runs unavailable"
          message="Your role does not permit running agents in this organization."
          icon={<Sparkles className="h-8 w-8" />}
        />
      )}

      {/* Form beside its output: stacked, the form was a single short card in an
          otherwise empty viewport, and it scrolled out of reach as soon as a run
          produced anything. */}
      {permitted && (
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4 lg:sticky lg:top-4">
      <Can permission="run_agents">
        <Card data-testid="multi-form-card">
          <CardHeader>
            <CardTitle>New multi-agent run</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="multi-task" className="text-sm font-medium text-text">
                Task
              </label>
              <Input
                id="multi-task"
                data-testid="multi-task"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Draft a briefing on the Q3 incident with sources…"
              />
              <ExampleChips
                testId="multi-examples"
                examples={MULTI_AGENT_EXAMPLES}
                onPick={setTask}
              />
            </div>
            {conversationId && (
              <p className="text-xs text-text-muted" data-testid="multi-conversation-context">
                Continuing conversation{" "}
                <span className="font-mono">{conversationId}</span>
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                data-testid="multi-start"
                loading={start.isPending}
                disabled={trimmed.length === 0}
                onClick={() => start.mutate()}
              >
                <PlayCircle className="h-4 w-4" aria-hidden="true" />
                Start run
              </Button>
            </div>
            {start.isError && (
              <div data-testid="multi-start-error">
                <ErrorBanner error={start.error} />
              </div>
            )}
          </CardContent>
        </Card>
      </Can>
      </div>

      <div className="flex min-w-0 flex-col gap-4" data-testid="multi-output">
      {/* Before a run exists, describe the collaboration the four roles perform.
          The page header names them but says nothing about what each contributes,
          and the column would otherwise be empty. */}
      {!run && (
        <Card data-testid="multi-idle">
          <CardHeader>
            <CardTitle className="text-base">No run yet</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <ol className="flex flex-col gap-2.5">
              {[
                {
                  role: "Planner",
                  does: "breaks the task into ordered steps.",
                  colour: "var(--color-role-planner)",
                },
                {
                  role: "Researcher",
                  does: "gathers findings from your documents, keeping each citation.",
                  colour: "var(--color-role-researcher)",
                },
                {
                  role: "Writer",
                  does: "drafts the answer from the plan and those findings.",
                  colour: "var(--color-role-writer)",
                },
                {
                  role: "Critic",
                  does: "checks the draft is supported and can send it back for revision.",
                  colour: "var(--color-role-critic)",
                },
              ].map((step, index) => (
                <li key={step.role} className="flex items-start gap-2.5 text-sm">
                  <span
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-text-inverted"
                    style={{ background: step.colour }}
                    aria-hidden="true"
                  >
                    {index + 1}
                  </span>
                  <span className="text-text-muted">
                    <span className="font-medium text-text">{step.role}</span>{" "}
                    {step.does}
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-sm leading-relaxed text-text-muted">
              A run may pause at an approval checkpoint and wait for you to
              approve, reject, or edit the draft.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Run summary (Req 10.1). */}
      {run && (
        <Card data-testid="multi-run-summary">
          <CardHeader>
            <CardTitle>Run started</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs uppercase tracking-wide text-text-muted">Run ID</dt>
                <dd data-testid="multi-run-id">
                  {/* Needed to look the run up later, so it has to be copyable
                      rather than a 36-character string to select by hand. */}
                  <CopyableId value={run.run_id} label="run id" testId="multi-run-id-copy" />
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs uppercase tracking-wide text-text-muted">
                  Conversation ID
                </dt>
                <dd data-testid="multi-conversation-id">
                  <CopyableId
                    value={run.conversation_id}
                    label="conversation id"
                    testId="multi-conversation-id-copy"
                  />
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs uppercase tracking-wide text-text-muted">Status</dt>
                <dd>
                  <Badge tone="info" data-testid="multi-status">
                    {run.status}
                  </Badge>
                </dd>
              </div>
            </dl>
            <Can permission="run_agents">
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  data-testid="multi-stream-open"
                  disabled={stream.isStreaming}
                  onClick={openStream}
                >
                  <Radio className="h-4 w-4" aria-hidden="true" />
                  Open live stream
                </Button>
                {stream.isStreaming && (
                  <Button
                    type="button"
                    variant="danger"
                    data-testid="multi-cancel"
                    onClick={() => stream.cancel()}
                  >
                    <StopCircle className="h-4 w-4" aria-hidden="true" />
                    Cancel
                  </Button>
                )}
                <Button
                  type="button"
                  variant="secondary"
                  data-testid="multi-result-load"
                  onClick={refreshResult}
                >
                  <ListTree className="h-4 w-4" aria-hidden="true" />
                  View persisted result
                </Button>
              </div>
            </Can>
          </CardContent>
        </Card>
      )}

      {/* Live workflow + ordered event log (Req 10.2). */}
      {hasStreamActivity && (
        <Card data-testid="multi-stream-card">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Live workflow</CardTitle>
              {stream.isStreaming && (
                <Badge tone="info" data-testid="multi-streaming-indicator">
                  Streaming…
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <WorkflowVisualizer state={streamState} />

            {/* Ordered event log (by sequence). */}
            {streamState.events.length > 0 && (
              <div className="flex flex-col gap-2" aria-live="polite">
                <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                  Event log
                </span>
                <ol className="flex flex-col gap-1" data-testid="multi-event-log">
                  {streamState.events.map((e, i) => {
                    const seq =
                      typeof e.data.sequence === "number" ? e.data.sequence : i;
                    const roleId = roleOf(e);
                    return (
                      <li
                        key={`${seq}-${i}`}
                        data-testid={`multi-event-${seq}`}
                        data-sequence={seq}
                        data-role={roleId ?? undefined}
                        className="flex flex-wrap items-center gap-2 text-xs text-text-muted"
                      >
                        <span className="font-mono text-text-muted">#{seq}</span>
                        <Badge tone="neutral">{e.type}</Badge>
                        {roleId && <Badge tone="primary">{roleId}</Badge>}
                        <span>{summarize(e)}</span>
                      </li>
                    );
                  })}
                </ol>
                {stream.isStreaming && <StreamingCursor />}
              </div>
            )}

            {/* Non-terminal approval checkpoint (Req 10.3, 10.4, 10.8). */}
            {streamState.approval && (
              <ApprovalPanel
                runId={streamState.approval.runId || run?.run_id || ""}
                checkpoint={streamState.approval.checkpoint}
                onConflict={refreshResult}
              />
            )}

            {/* Completion → final output + citations (Req 10.5). */}
            {streamState.closed && streamState.terminal?.type === "completion" && (
              <div className="flex flex-col gap-3" data-testid="multi-final-output">
                <Markdown
                  content={streamState.finalAnswer ?? ""}
                  citations={streamState.citations}
                />
                {streamState.terminationReason && (
                  <Badge tone="neutral" data-testid="multi-termination-reason">
                    {streamState.terminationReason}
                  </Badge>
                )}
                {streamState.citations.length > 0 && (
                  <ul className="flex flex-col gap-1" data-testid="multi-citations">
                    {streamState.citations.map((c, i) => (
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
                )}
              </div>
            )}

            {/* Error terminal. */}
            {streamState.closed && streamState.terminal?.type === "error" && (
              <p className="text-sm text-danger" data-testid="multi-stream-error">
                {streamState.errorMessage}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stream transport/open error. */}
      {stream.error && (
        <div data-testid="multi-stream-transport-error">
          <ErrorBanner error={stream.error} />
        </div>
      )}

      {/* Persisted run result (Req 10.6, 10.7). */}
      {run && showResult && (
        <Card data-testid="multi-result-card">
          <CardHeader>
            <CardTitle>Run result</CardTitle>
          </CardHeader>
          <CardContent>
            <MultiAgentRunResult runId={run.run_id} refreshToken={resultRefresh} />
          </CardContent>
        </Card>
      )}
      </div>
      </div>
      )}
    </div>
  );
}
