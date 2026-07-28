/**
 * `WorkspaceStats`: live, at-a-glance workspace metrics for the Dashboard.
 *
 * Replaces the previously static landing page with real numbers for the active
 * Org_Context: how many documents are in the corpus and the all-time token
 * usage + estimated cost. Each metric is fetched independently and degrades
 * gracefully — a per-tile skeleton while loading and a neutral em dash on
 * error — so a single failing endpoint never blocks the dashboard. Gated behind
 * `read`; renders nothing for a role without it.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins, FileText, Hash, type LucideIcon } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { StatCard, type StatTone } from "../../components/ui/StatCard";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatCost } from "../analytics/formatCost";

interface DocumentSummary {
  document_id: string;
}

interface UsageSummary {
  total_tokens: number;
  total_cost: string;
}

/** Render a stat value with resilient loading / error fallbacks. */
function StatValue({
  isLoading,
  isError,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  children: React.ReactNode;
}): JSX.Element {
  if (isLoading) return <Skeleton className="h-7 w-20" />;
  if (isError) return <span className="text-text-subtle">—</span>;
  return <>{children}</>;
}

export function WorkspaceStats(): JSX.Element | null {
  const { orgId, role } = useSession();
  const canRead = role !== null && can(role, "read");

  const documents = useQuery<DocumentSummary[], ClientError>({
    enabled: canRead,
    queryKey: orgScopedKey(orgId, "documents"),
    queryFn: () => runRequest(() => apiClient.GET("/documents")),
    retry: false,
    staleTime: 30_000,
  });

  const usage = useQuery<UsageSummary, ClientError>({
    enabled: canRead,
    queryKey: orgScopedKey(orgId, "usage-summary"),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/analytics/usage", { params: { query: {} } }),
      );
      return { total_tokens: data.total_tokens, total_cost: data.total_cost };
    },
    retry: false,
    staleTime: 30_000,
  });

  if (!canRead) return null;

  // Defensive against a non-array documents payload (e.g. an error/mocked body).
  const docCount = Array.isArray(documents.data) ? documents.data.length : 0;
  const tokens =
    typeof usage.data?.total_tokens === "number" ? usage.data.total_tokens : 0;
  const cost =
    typeof usage.data?.total_cost === "string" ? usage.data.total_cost : "0";

  const tiles: {
    label: string;
    icon: LucideIcon;
    tone: StatTone;
    hint: string;
    testId: string;
    isLoading: boolean;
    isError: boolean;
    value: React.ReactNode;
  }[] = [
    {
      label: "Documents",
      icon: FileText,
      tone: "primary",
      hint: "in your corpus",
      testId: "stat-documents",
      isLoading: documents.isLoading,
      isError: documents.isError,
      value: docCount.toLocaleString(),
    },
    {
      label: "Tokens used",
      icon: Hash,
      tone: "info",
      hint: "all-time",
      testId: "stat-tokens",
      isLoading: usage.isLoading,
      isError: usage.isError,
      value: tokens.toLocaleString(),
    },
    {
      label: "Estimated cost",
      icon: Coins,
      tone: "success",
      hint: "all-time",
      testId: "stat-cost",
      isLoading: usage.isLoading,
      isError: usage.isError,
      value: formatCost(cost),
    },
  ];

  return (
    <section
      className="grid grid-cols-1 gap-4 sm:grid-cols-3"
      data-testid="workspace-stats"
      aria-label="Workspace statistics"
    >
      {tiles.map((t) => (
        <StatCard
          key={t.testId}
          label={t.label}
          icon={t.icon}
          tone={t.tone}
          hint={t.hint}
          data-testid={t.testId}
          value={
            <StatValue isLoading={t.isLoading} isError={t.isError}>
              {t.value}
            </StatValue>
          }
        />
      ))}
    </section>
  );
}
