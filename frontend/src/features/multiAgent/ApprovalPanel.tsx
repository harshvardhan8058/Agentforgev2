/**
 * `ApprovalPanel`: the human approval checkpoint (Req 10.3, 10.4, 10.8).
 *
 * Rendered when the multi-agent stream reports a **non-terminal**
 * `approval_required` pause. It is an elevated, first-class interactive panel —
 * visually distinct as a pause ("waiting on you"), never conflated with a
 * terminal completion — offering `approve` / `reject` / `edit` actions
 * (Req 10.3). Submitting calls `POST /multi-agent/runs/{run_id}/approval` with
 * the decision type and any feedback / edited content, then shows the returned
 * `status` and `termination_reason` (Req 10.4).
 *
 * A `409 run-not-awaiting-approval` surfaces a message and asks the parent to
 * refresh the run status (Req 10.8).
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Check, PauseCircle, Pencil, X } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";

type Decision = "approve" | "reject" | "edit";

interface ApprovalDecisionResult {
  run_id: string;
  status: "running" | "awaiting_approval" | "terminated";
  termination_reason?:
    | "completed"
    | "max-rounds-reached"
    | "max-revisions-reached"
    | "rejected"
    | "aborted"
    | null;
}

export function ApprovalPanel({
  runId,
  checkpoint,
  onConflict,
}: {
  runId: string;
  checkpoint: string;
  /** Invoked on a `409 run-not-awaiting-approval` so the parent can refresh. */
  onConflict?: () => void;
}): JSX.Element {
  const [mode, setMode] = useState<Decision | null>(null);
  const [feedback, setFeedback] = useState("");
  const [editedContent, setEditedContent] = useState("");

  const submit = useMutation<
    ApprovalDecisionResult,
    ClientError,
    { type: Decision; feedback?: string; edited_content?: string }
  >({
    mutationFn: (body) =>
      runRequest<ApprovalDecisionResult>(() =>
        apiClient.POST("/multi-agent/runs/{run_id}/approval", {
          params: { path: { run_id: runId } },
          body,
        }),
      ),
    onError: (err) => {
      if (err.status === 409) onConflict?.();
    },
  });

  const result = submit.data;

  function submitApprove(): void {
    submit.mutate({ type: "approve" });
  }
  function submitReject(): void {
    submit.mutate({ type: "reject", feedback: feedback.trim() || undefined });
  }
  function submitEdit(): void {
    submit.mutate({
      type: "edit",
      edited_content: editedContent,
      feedback: feedback.trim() || undefined,
    });
  }

  return (
    <Card
      raised
      data-testid="approval-panel"
      className="border-warning/50 ring-1 ring-warning/30"
    >
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-warning">
            <PauseCircle className="h-5 w-5" aria-hidden="true" />
            Waiting on you
          </CardTitle>
          <Badge tone="warning" data-testid="approval-pause-indicator">
            Paused — approval required
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {checkpoint && (
          <p className="text-sm text-text" data-testid="approval-checkpoint">
            {checkpoint}
          </p>
        )}

        {/* Decision actions (Req 10.3). */}
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            data-testid="approval-approve"
            loading={submit.isPending && submit.variables?.type === "approve"}
            onClick={submitApprove}
          >
            <Check className="h-4 w-4" aria-hidden="true" />
            Approve
          </Button>
          <Button
            type="button"
            variant="danger"
            data-testid="approval-reject"
            onClick={() => setMode((m) => (m === "reject" ? null : "reject"))}
          >
            <X className="h-4 w-4" aria-hidden="true" />
            Reject
          </Button>
          <Button
            type="button"
            variant="secondary"
            data-testid="approval-edit"
            onClick={() => setMode((m) => (m === "edit" ? null : "edit"))}
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
            Edit
          </Button>
        </div>

        {/* Reject: optional feedback then confirm. */}
        {mode === "reject" && (
          <div className="flex flex-col gap-2" data-testid="approval-reject-form">
            <label htmlFor="approval-feedback" className="text-sm font-medium text-text">
              Feedback (optional)
            </label>
            <Input
              id="approval-feedback"
              data-testid="approval-feedback"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Why is this rejected?"
            />
            <Button
              type="button"
              variant="danger"
              data-testid="approval-reject-confirm"
              loading={submit.isPending && submit.variables?.type === "reject"}
              onClick={submitReject}
            >
              Submit rejection
            </Button>
          </div>
        )}

        {/* Edit: replacement content then confirm. */}
        {mode === "edit" && (
          <div className="flex flex-col gap-2" data-testid="approval-edit-form">
            <label htmlFor="approval-edited" className="text-sm font-medium text-text">
              Edited content
            </label>
            <Input
              id="approval-edited"
              data-testid="approval-edited-content"
              value={editedContent}
              onChange={(e) => setEditedContent(e.target.value)}
              placeholder="Replacement content…"
            />
            <Button
              type="button"
              data-testid="approval-edit-confirm"
              loading={submit.isPending && submit.variables?.type === "edit"}
              onClick={submitEdit}
            >
              Submit edit
            </Button>
          </div>
        )}

        {/* 409 run-not-awaiting-approval (Req 10.8). */}
        {submit.isError && submit.error.status === 409 && (
          <p className="text-sm text-warning" data-testid="approval-conflict">
            This run is no longer awaiting approval. Refreshing its status…
          </p>
        )}
        {/* Any other failure surfaces uniformly. */}
        {submit.isError && submit.error.status !== 409 && (
          <div data-testid="approval-error">
            <ErrorBanner error={submit.error} />
          </div>
        )}

        {/* Decision response (Req 10.4). */}
        {result && (
          <div
            className="flex flex-wrap items-center gap-2"
            data-testid="approval-result"
          >
            <span className="text-sm text-text-muted">Decision applied:</span>
            <Badge tone="info" data-testid="approval-status">
              {result.status}
            </Badge>
            {result.termination_reason && (
              <Badge tone="neutral" data-testid="approval-termination-reason">
                {result.termination_reason}
              </Badge>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
