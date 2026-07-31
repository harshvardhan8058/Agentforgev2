/**
 * `GuardrailsView`: the guardrail configuration + evaluate surface
 * (`/guardrails`, Req 13.1–13.5, 4.2).
 *
 * `GET /guardrails/config` renders each active guardrail's `name`/`kind` in the
 * returned order as an ordered list of cards. `POST /guardrails/evaluate`
 * (gated behind `run_agents`) shows the `allow` / `flag` / `block` decision in
 * visually distinct states — `flag` shows flags + reason; `block` shows the
 * reason. An empty config renders an explicit no-active-guardrails state.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { Skeleton } from "../../components/ui/Skeleton";
import { GUARDRAIL_EXAMPLES } from "../../lib/examples";
import { describeGuardrail } from "./guardrailCatalog";

interface GuardrailInfo {
  name: string;
  kind: string;
}
interface GuardrailConfig {
  guardrails: GuardrailInfo[];
}
type Decision = "allow" | "flag" | "block";
interface EvaluateResult {
  decision: Decision;
  flags: string[];
  reason?: string | null;
}

const DECISION_TONE: Record<Decision, BadgeTone> = {
  allow: "success",
  flag: "warning",
  block: "danger",
};

export function GuardrailsView(): JSX.Element {
  const { orgId } = useSession();
  const [content, setContent] = useState("");

  const config = useQuery<GuardrailConfig, ClientError>({
    queryKey: orgScopedKey(orgId, "guardrails-config"),
    queryFn: async () => {
      const data = await runRequest(() => apiClient.GET("/guardrails/config"));
      return { guardrails: data.guardrails ?? [] };
    },
  });

  const evaluate = useMutation<EvaluateResult, ClientError, void>({
    mutationFn: async () => {
      const data = await runRequest(() =>
        apiClient.POST("/guardrails/evaluate", { body: { content } }),
      );
      return { decision: data.decision, flags: data.flags ?? [], reason: data.reason ?? null };
    },
  });

  const guardrails = config.data?.guardrails ?? [];
  const result = evaluate.data;

  return (
    <div className="flex flex-col gap-6" data-testid="guardrails-view">
      <PageHeader
        eyebrow="Platform"
        icon={ShieldCheck}
        title="Guardrails"
        description="Inspect the active safety pipeline and evaluate content against it."
      />

      <Card data-testid="guardrails-config-card">
        <CardHeader>
          <CardTitle className="text-base">Active guardrails</CardTitle>
        </CardHeader>
        <CardContent>
          {config.isLoading && <Skeleton className="h-24 w-full" data-testid="config-skeleton" />}
          {config.isError && <ErrorBanner error={config.error} onRetry={() => void config.refetch()} />}
          {config.data && guardrails.length === 0 && (
            <div data-testid="guardrails-empty">
              <EmptyState
                title="No active guardrails"
                message="This organization has no guardrails configured."
                icon={<ShieldCheck className="h-8 w-8" />}
              />
            </div>
          )}
          {guardrails.length > 0 && (
            <ol className="flex flex-col gap-2" data-testid="guardrails-list">
              {guardrails.map((g, i) => {
                const described = describeGuardrail(g.name);
                return (
                  <li
                    key={`${g.name}-${i}`}
                    data-testid={`guardrail-${i}`}
                    className="flex flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {/* The order is the order the pipeline applies them, so it
                          is worth stating rather than leaving implicit. */}
                      <span className="text-xs tabular-nums text-text-subtle">
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium text-text">
                        {described.label}
                      </span>
                      {/* The stable API name, and the implementation class only as
                          a tooltip: useful for support, not a headline. */}
                      <code
                        className="rounded bg-bg-subtle px-1.5 py-0.5 font-mono text-xs text-text-muted"
                        title={`Implementation: ${g.kind}`}
                        data-testid={`guardrail-name-${i}`}
                      >
                        {g.name}
                      </code>
                    </div>
                    {described.description && (
                      <p
                        className="text-xs leading-relaxed text-text-muted"
                        data-testid={`guardrail-description-${i}`}
                      >
                        {described.description}
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>

      <Can permission="run_agents">
        <Card data-testid="evaluate-card">
          <CardHeader>
            <CardTitle className="text-base">Evaluate content</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3"
              data-testid="evaluate-form"
              onSubmit={(e) => {
                e.preventDefault();
                evaluate.mutate();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <label htmlFor="guardrail-content" className="text-sm font-medium text-text">
                  Content
                </label>
                <Input
                  id="guardrail-content"
                  data-testid="guardrail-content"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Paste content to check against the pipeline…"
                />
                {/* Presets that exercise the guardrails active by default. The
                    blocklist is empty unless GUARDRAIL_BLOCKLIST_JSON is set, so
                    no preset here claims to trip it. */}
                <ExampleChips
                  examples={GUARDRAIL_EXAMPLES}
                  onPick={setContent}
                  testId="guardrail-examples"
                />
              </div>
              <div>
                <Button type="submit" data-testid="evaluate-submit" loading={evaluate.isPending}>
                  Evaluate
                </Button>
              </div>
            </form>

            {evaluate.isError && (
              <div className="mt-3" data-testid="evaluate-error">
                <ErrorBanner error={evaluate.error} />
              </div>
            )}

            {result && (
              <div
                className="mt-4 flex flex-col gap-2 rounded-lg border border-border bg-surface p-3"
                data-testid="evaluate-result"
                data-decision={result.decision}
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm text-text-muted">Decision</span>
                  <Badge tone={DECISION_TONE[result.decision]} data-testid="decision-badge">
                    {result.decision}
                  </Badge>
                </div>

                {result.decision === "flag" && (
                  <div className="flex flex-col gap-1.5" data-testid="decision-flag-detail">
                    {result.flags.length > 0 && (
                      <div className="flex flex-wrap gap-1.5" data-testid="decision-flags">
                        {result.flags.map((f) => (
                          <Badge key={f} tone="warning" data-testid={`decision-flag-${f}`}>
                            {f}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {result.reason && (
                      <p className="text-sm text-text-muted" data-testid="decision-reason">
                        {result.reason}
                      </p>
                    )}
                  </div>
                )}

                {result.decision === "block" && result.reason && (
                  <p className="text-sm text-danger" data-testid="decision-reason">
                    {result.reason}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </Can>
    </div>
  );
}
