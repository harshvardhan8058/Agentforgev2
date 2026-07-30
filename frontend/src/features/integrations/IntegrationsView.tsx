/**
 * `IntegrationsView`: the connections + model-provider surface (`/integrations`).
 *
 * The backend has always shipped `GET /integrations/status`, but no frontend
 * route reached it — so the connector feature was effectively invisible. This
 * view exposes it directly:
 *
 *  - **Language model** — derived from `GET /analytics/usage`'s `by_provider`
 *    breakdown. This is the only read-only signal the API exposes for which LLM
 *    actually served traffic, and it answers the single most common point of
 *    confusion: keyless installs run a deterministic fallback provider, so
 *    answers look like echoed prompt text rather than a real completion.
 *  - **Connected services** — each connector's `{name, enabled}` status.
 *
 * Both endpoints require only `read`. The status payload is intentionally
 * credential-free (name + enabled only), so nothing secret can surface here;
 * enabling a connector is an operator/deployment action, which the view explains
 * rather than pretending to offer an in-app connect flow that no API backs.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleSlash,
  Github,
  HardDrive,
  Info,
  Mail,
  MessageSquare,
  Plug,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { PageHeader } from "../../components/ui/PageHeader";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";

interface IntegrationStatus {
  name: string;
  enabled: boolean;
}

interface ProviderUsage {
  key: string;
  total_tokens: number;
}

/**
 * Presentation metadata for the connectors the backend can report. Unknown
 * names still render (title-cased with a generic icon) so a newly added
 * backend connector is never silently hidden.
 */
const CONNECTORS: Record<string, { label: string; icon: LucideIcon; blurb: string }> = {
  slack: {
    label: "Slack",
    icon: MessageSquare,
    blurb: "Post agent results and notifications into channels.",
  },
  gmail: {
    label: "Gmail",
    icon: Mail,
    blurb: "Read and send mail as part of an agent workflow.",
  },
  google_drive: {
    label: "Google Drive",
    icon: HardDrive,
    blurb: "Pull documents from Drive into your corpus.",
  },
  github: {
    label: "GitHub",
    icon: Github,
    blurb: "Read repository content and act on issues.",
  },
};

function connectorMeta(name: string): { label: string; icon: LucideIcon; blurb: string } {
  return (
    CONNECTORS[name] ?? {
      label: name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      icon: Plug,
      blurb: "Configured on the server.",
    }
  );
}

/** The deterministic, credential-free provider used when no LLM key is set. */
const FALLBACK_PROVIDER = "fallback";

export function IntegrationsView(): JSX.Element {
  const { orgId } = useSession();

  const status = useQuery<IntegrationStatus[], ClientError>({
    queryKey: orgScopedKey(orgId, "integrations-status"),
    queryFn: async () => {
      const data = await runRequest(() => apiClient.GET("/integrations/status"));
      return Array.isArray(data.integrations) ? data.integrations : [];
    },
  });

  const providers = useQuery<
    { byProvider: ProviderUsage[]; byModel: ProviderUsage[] },
    ClientError
  >({
    queryKey: orgScopedKey(orgId, "usage-providers"),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/analytics/usage", { params: { query: {} } }),
      );
      return {
        byProvider: Array.isArray(data.by_provider) ? data.by_provider : [],
        byModel: Array.isArray(data.by_model) ? data.by_model : [],
      };
    },
    retry: false,
    staleTime: 30_000,
  });

  const integrations = status.data ?? [];

  // Only providers that actually served traffic are meaningful signals.
  const active = (providers.data?.byProvider ?? []).filter((p) => p.total_tokens > 0);
  const usingFallback = active.some((p) => p.key === FALLBACK_PROVIDER);
  const realProviders = active.filter((p) => p.key !== FALLBACK_PROVIDER);
  // The concrete models observed, excluding the keyless fallback's own label so
  // it is not presented as if it were a model.
  const models = (providers.data?.byModel ?? []).filter(
    (m) => m.total_tokens > 0 && m.key !== FALLBACK_PROVIDER,
  );

  return (
    <div className="flex flex-col gap-6" data-testid="integrations-view">
      <PageHeader
        eyebrow="Platform"
        icon={Plug}
        title="Integrations"
        description="See which language model is serving your traffic and which external services are connected."
      />

      {/* ---- Language model provider ---- */}
      <Card data-testid="model-provider-card">
        <CardHeader>
          <CardTitle className="text-base">Language model</CardTitle>
        </CardHeader>
        <CardContent>
          {providers.isLoading && (
            <Skeleton className="h-16 w-full" data-testid="model-provider-skeleton" />
          )}

          {providers.isError && (
            <ErrorBanner error={providers.error} onRetry={() => void providers.refetch()} />
          )}

          {providers.data && active.length === 0 && (
            <div
              className="flex items-start gap-3 rounded-lg border border-border bg-surface-raised p-4"
              data-testid="model-provider-unknown"
            >
              <Info className="mt-0.5 h-5 w-5 shrink-0 text-text-muted" aria-hidden="true" />
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium text-text">No model calls recorded yet</span>
                <span className="text-sm text-text-muted">
                  Run a query or an agent, then return here to see which provider served it.
                </span>
              </div>
            </div>
          )}

          {/* A healthy hosted provider previously rendered as a single small
              badge alone in a large card, which said almost nothing: not what it
              means, not which model, not how much it has served. */}
          {realProviders.length > 0 && (
            <div className="flex flex-col gap-3" data-testid="model-provider-active">
              <div className="flex flex-col gap-2">
                {realProviders.map((p) => (
                  <div
                    key={p.key}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2"
                  >
                    <span className="flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full bg-success"
                        aria-hidden="true"
                      />
                      <Badge tone="success" data-testid={`model-provider-${p.key}`}>
                        {p.key}
                      </Badge>
                      <span className="text-sm text-text">serving your traffic</span>
                    </span>
                    <span
                      className="text-xs tabular-nums text-text-muted"
                      data-testid={`model-provider-tokens-${p.key}`}
                    >
                      {p.total_tokens.toLocaleString("en-US")} tokens
                    </span>
                  </div>
                ))}
              </div>
              {models.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-text-subtle">Models seen:</span>
                  {models.map((m) => (
                    <code
                      key={m.key}
                      className="rounded bg-bg-subtle px-1.5 py-0.5 font-mono text-xs text-text-muted"
                      data-testid={`model-name-${m.key}`}
                    >
                      {m.key}
                    </code>
                  ))}
                </div>
              )}
              <p className="text-sm leading-relaxed text-text-muted">
                Answers are written by the model. Credentials are read from the
                server environment and are never sent to the browser.
              </p>
            </div>
          )}

          {usingFallback && (
            <div
              className={cn(
                "flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/15 p-4",
                realProviders.length > 0 && "mt-3",
              )}
              data-testid="model-provider-fallback"
            >
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text">
                  Running on the built-in fallback provider
                </span>
                <p className="text-sm text-text-muted">
                  AgentForge boots with no credentials, so a deterministic offline provider answers
                  every request. Retrieval, citations, guardrails and the full agent workflow are all
                  real — but the wording is generated from your prompt and context rather than by a
                  model, which is why answers can read like echoed text.
                </p>
                <p className="text-sm text-text-muted">
                  To get model-written answers, set a provider key such as{" "}
                  <code className="rounded bg-bg-subtle px-1 py-0.5 font-mono text-xs">
                    GROQ_API_KEY
                  </code>{" "}
                  in the server environment and restart the API. Credentials live only on the server
                  and are never exposed to the browser.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- External connectors ---- */}
      <Card data-testid="connectors-card">
        <CardHeader>
          <CardTitle className="text-base">Connected services</CardTitle>
        </CardHeader>
        <CardContent>
          {status.isLoading && (
            <Skeleton className="h-32 w-full" data-testid="connectors-skeleton" />
          )}

          {status.isError && (
            <ErrorBanner error={status.error} onRetry={() => void status.refetch()} />
          )}

          {status.data && integrations.length === 0 && (
            <div data-testid="connectors-empty">
              <EmptyState
                title="No integrations available"
                message="This deployment reports no external connectors."
                icon={<Plug className="h-8 w-8" />}
              />
            </div>
          )}

          {integrations.length > 0 && (
            <>
              <ul
                className="grid grid-cols-1 gap-3 sm:grid-cols-2"
                data-testid="connectors-list"
              >
                {integrations.map((item) => {
                  const meta = connectorMeta(item.name);
                  const Icon = meta.icon;
                  return (
                    <li
                      key={item.name}
                      data-testid={`connector-${item.name}`}
                      data-enabled={item.enabled}
                      className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4"
                    >
                      <span
                        className={cn(
                          "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                          item.enabled
                            ? "bg-success/15 text-success"
                            : "bg-surface-raised text-text-subtle",
                        )}
                        aria-hidden="true"
                      >
                        <Icon className="h-4 w-4" />
                      </span>
                      <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <span
                            className="text-sm font-medium text-text"
                            data-testid={`connector-name-${item.name}`}
                          >
                            {meta.label}
                          </span>
                          <Badge
                            tone={item.enabled ? "success" : "neutral"}
                            data-testid={`connector-state-${item.name}`}
                          >
                            {item.enabled ? (
                              <span className="inline-flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                                Enabled
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1">
                                <CircleSlash className="h-3 w-3" aria-hidden="true" />
                                Not configured
                              </span>
                            )}
                          </Badge>
                        </div>
                        <span className="text-sm text-text-muted">{meta.blurb}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>

              <p className="mt-4 text-sm text-text-subtle" data-testid="connectors-note">
                Connectors are enabled by supplying their credentials in the server environment.
                AgentForge reports only a name and an on/off state — no tokens or secrets are ever
                returned to the browser.
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
