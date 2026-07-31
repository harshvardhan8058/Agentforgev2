/**
 * `TraceExportNotice`: says whether the trace on screen goes anywhere else.
 *
 * Traces are always *recorded* by the backend, but *export* to an external
 * destination (LangSmith, an OTLP collector) depends on a server credential. A
 * trace surface therefore had an ambiguity a user could not resolve: nothing
 * distinguished "this deployment does not export traces" from "export is
 * configured and this run simply has not appeared upstream yet". Both look
 * identical — an empty external dashboard.
 *
 * This reads `GET /observability/status`, which reports what the process will
 * actually do (a configured exporter with nothing to read from reports
 * `enabled: false`), and states it in one muted line.
 *
 * It is deliberately quiet about failure: if the status call fails, the notice
 * renders nothing rather than an error banner. It is contextual information
 * beside a trace that rendered fine on its own, so an error here would report a
 * problem the user cannot act on and did not ask about.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Radio, RadioTower } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";

/** Mirrors the generated `ObservabilityStatusResponse`. */
interface ObservabilityStatus {
  trace_export: {
    enabled: boolean;
    exporter: string;
    destination?: string | null;
  };
}

/** Human label for an exporter identifier; unknown names are shown verbatim. */
const EXPORTER_LABELS: Record<string, string> = {
  langsmith: "LangSmith",
  otlp: "an OpenTelemetry collector",
};

export function TraceExportNotice(): JSX.Element | null {
  const { orgId } = useSession();

  // Deployment-wide, so it is fetched once and shared by every trace on screen.
  // `staleTime` keeps expanding several runs from re-requesting it: the value only
  // changes when the server is reconfigured and restarted.
  const status = useQuery<ObservabilityStatus, ClientError>({
    queryKey: orgScopedKey(orgId, "observability-status"),
    staleTime: 5 * 60 * 1000,
    queryFn: () =>
      runRequest<ObservabilityStatus>(() =>
        apiClient.GET("/observability/status", {}),
      ),
  });

  if (status.data === undefined) return null;

  const { enabled, exporter, destination } = status.data.trace_export;
  const label = EXPORTER_LABELS[exporter] ?? exporter;

  return (
    <p
      className="mt-3 flex items-center gap-1.5 text-xs text-text-subtle"
      data-testid="trace-export-notice"
      data-export-enabled={enabled}
    >
      {enabled ? (
        <>
          <RadioTower className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Recorded here and exported to {label}
            {destination ? (
              <>
                {" "}
                (project <span className="font-mono">{destination}</span>)
              </>
            ) : null}
            .
          </span>
        </>
      ) : (
        <>
          <Radio className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Recorded in this deployment only — external trace export is off.
          </span>
        </>
      )}
    </p>
  );
}
