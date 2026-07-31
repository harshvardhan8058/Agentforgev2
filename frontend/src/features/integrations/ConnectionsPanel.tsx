/**
 * `ConnectionsPanel`: per-org, non-secret integration configuration.
 *
 * Binds to the `/integrations/connections` contract:
 *  - `GET    /integrations/connections`        — the org's stored configs (`read`)
 *  - `POST   /integrations/connections`        — add config for one integration
 *  - `PATCH  /integrations/connections/{id}`   — replace a config
 *  - `DELETE /integrations/connections/{id}`   — remove a config
 *
 * Reading needs only `read` (the records are non-secret by construction); every mutation
 * is wrapped in `<Can permission="manage_integrations">`, so a role without it has the
 * controls absent from the DOM rather than disabled.
 *
 * Two things this panel is careful **not** to imply:
 *  - config does not enable anything. Enablement is a pure function of the server's
 *    credentials, reported separately by `GET /integrations/status`, so the copy says so
 *    instead of letting a saved config read as "connected".
 *  - the credential rule is not re-implemented here. The server refuses a
 *    credential-shaped setting and its message is surfaced verbatim.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plug, Save, SlidersHorizontal, Trash2 } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import type { Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTrigger,
} from "../../components/ui/Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSelectTrigger,
} from "../../components/ui/DropdownMenu";
import { Skeleton } from "../../components/ui/Skeleton";
import {
  ConnectionConfigEditor,
  emptyRow,
  rowsFromConfig,
  toConfig,
  type ConfigRow,
} from "./ConnectionConfigEditor";

const MANAGE_INTEGRATIONS: Permission = "manage_integrations";

/**
 * Mirrors the generated `IntegrationConnectionResponse`. `config` values are JSON
 * scalars, which is what the contract declares and the server accepts.
 */
type ConfigValue = string | number | boolean | null;

interface IntegrationConnection {
  connection_id: string;
  integration: string;
  config?: Record<string, ConfigValue>;
  created_at: string;
}

/** One editable config row set, keyed by the connection being edited. */
interface EditState {
  connectionId: string;
  rows: ConfigRow[];
}

export function ConnectionsPanel({
  /** Integration names the deployment reports, used to populate the picker. */
  integrationNames,
}: {
  integrationNames: readonly string[];
}): JSX.Element {
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const listKey = orgScopedKey(orgId, "integration-connections");

  const [newIntegration, setNewIntegration] = useState<string | null>(null);
  const [newRows, setNewRows] = useState<ConfigRow[]>([emptyRow()]);
  const [edit, setEdit] = useState<EditState | null>(null);

  const connections = useQuery<IntegrationConnection[], ClientError>({
    queryKey: listKey,
    queryFn: () =>
      runRequest<IntegrationConnection[]>(() =>
        apiClient.GET("/integrations/connections"),
      ),
  });

  function refresh(): void {
    void queryClient.invalidateQueries({ queryKey: listKey });
  }

  const create = useMutation<IntegrationConnection, ClientError, void>({
    mutationFn: () =>
      runRequest<IntegrationConnection>(() =>
        apiClient.POST("/integrations/connections", {
          body: { integration: selectedIntegration, config: toConfig(newRows) },
        }),
      ),
    onSuccess: (created) => {
      toast({
        title: "Configuration saved",
        description: created.integration,
        tone: "success",
      });
      setNewRows([emptyRow()]);
      refresh();
    },
  });

  const save = useMutation<IntegrationConnection, ClientError, EditState>({
    mutationFn: (state) =>
      runRequest<IntegrationConnection>(() =>
        apiClient.PATCH("/integrations/connections/{connection_id}", {
          params: { path: { connection_id: state.connectionId } },
          body: { config: toConfig(state.rows) },
        }),
      ),
    onSuccess: (updated) => {
      toast({
        title: "Configuration updated",
        description: updated.integration,
        tone: "success",
      });
      setEdit(null);
      refresh();
    },
  });

  const remove = useMutation<void, ClientError, IntegrationConnection>({
    mutationFn: (connection) =>
      runRequest<void>(() =>
        apiClient.DELETE("/integrations/connections/{connection_id}", {
          params: { path: { connection_id: connection.connection_id } },
        }),
      ),
    onSuccess: (_data, connection) => {
      toast({
        title: "Configuration removed",
        description: connection.integration,
        tone: "success",
      });
      if (edit?.connectionId === connection.connection_id) setEdit(null);
      refresh();
    },
  });

  const stored = connections.data ?? [];
  // Default the picker to the first reported integration rather than forcing a choice
  // for a deployment that only has one.
  const selectedIntegration = newIntegration ?? integrationNames[0] ?? "";

  return (
    <Card data-testid="connections-config-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <SlidersHorizontal className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Connection settings
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-text-muted">
          Non-secret, per-organization settings for a connector — a default Slack channel,
          a repository name. Saving settings does not connect or enable an integration:
          that depends on the server holding its credential, shown above.
        </p>

        {connections.isError && (
          <ErrorBanner
            error={connections.error}
            onRetry={() => void connections.refetch()}
          />
        )}

        {connections.isLoading && (
          <Skeleton className="h-20 w-full" data-testid="connections-config-skeleton" />
        )}

        {connections.data && stored.length === 0 && (
          <p className="text-sm text-text-subtle" data-testid="connections-config-empty">
            No connector settings stored for this organization.
          </p>
        )}

        {stored.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="connections-config-list">
            {stored.map((connection) => {
              const entries = Object.entries(connection.config ?? {});
              const editing = edit?.connectionId === connection.connection_id;
              return (
                <li
                  key={connection.connection_id}
                  className="rounded-lg border border-border bg-surface p-3"
                  data-testid={`connection-${connection.connection_id}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="primary">{connection.integration}</Badge>
                    {entries.length === 0 && (
                      <span className="text-xs text-text-subtle">no settings</span>
                    )}
                    <span className="ml-auto" />
                    <Can permission={MANAGE_INTEGRATIONS}>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        data-testid={`edit-connection-${connection.connection_id}`}
                        onClick={() =>
                          setEdit(
                            editing
                              ? null
                              : {
                                  connectionId: connection.connection_id,
                                  rows: rowsFromConfig(connection.config ?? {}),
                                },
                          )
                        }
                      >
                        {editing ? "Cancel" : "Edit"}
                      </Button>
                      <Dialog>
                        <DialogTrigger asChild>
                          <Button
                            type="button"
                            variant="danger"
                            size="sm"
                            data-testid={`remove-connection-${connection.connection_id}`}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                            Remove
                          </Button>
                        </DialogTrigger>
                        <DialogContent
                          title="Remove connector settings?"
                          description={`The stored settings for ${connection.integration} are deleted. The connector itself is unaffected — its availability depends on the server's credentials.`}
                        >
                          <div className="flex justify-end gap-2">
                            <DialogClose asChild>
                              <Button type="button" variant="secondary" size="sm">
                                Cancel
                              </Button>
                            </DialogClose>
                            <DialogClose asChild>
                              <Button
                                type="button"
                                variant="danger"
                                size="sm"
                                data-testid={`confirm-remove-connection-${connection.connection_id}`}
                                onClick={() => remove.mutate(connection)}
                              >
                                Remove settings
                              </Button>
                            </DialogClose>
                          </div>
                        </DialogContent>
                      </Dialog>
                    </Can>
                  </div>

                  {entries.length > 0 && !editing && (
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                      {entries.map(([key, value]) => (
                        <div key={key} className="contents">
                          <dt className="font-mono text-xs text-text-muted">{key}</dt>
                          <dd className="truncate text-text">{String(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}

                  {editing && edit && (
                    <div className="mt-3 flex flex-col gap-2">
                      <ConnectionConfigEditor
                        idPrefix={`edit-${connection.connection_id}`}
                        rows={edit.rows}
                        onChange={(rows) => setEdit({ ...edit, rows })}
                      />
                      <div>
                        <Button
                          type="button"
                          size="sm"
                          loading={save.isPending}
                          data-testid={`save-connection-${connection.connection_id}`}
                          onClick={() => save.mutate(edit)}
                        >
                          <Save className="h-4 w-4" aria-hidden="true" />
                          Save settings
                        </Button>
                      </div>
                      {save.isError && <ErrorBanner error={save.error} />}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {remove.isError && <ErrorBanner error={remove.error} />}

        <Can permission={MANAGE_INTEGRATIONS}>
          <div
            className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-3"
            data-testid="add-connection-form"
          >
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="new-connection-integration"
                className="text-sm font-medium text-text"
              >
                Connector
              </label>
              <DropdownMenu>
                <DropdownMenuSelectTrigger
                  id="new-connection-integration"
                  data-testid="new-connection-integration"
                  className="w-56"
                  value={selectedIntegration}
                  placeholder="Select a connector"
                />
                <DropdownMenuContent>
                  {integrationNames.map((name) => (
                    <DropdownMenuItem
                      key={name}
                      data-testid={`new-connection-integration-${name}`}
                      onSelect={() => setNewIntegration(name)}
                    >
                      {name}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <ConnectionConfigEditor
              idPrefix="new-connection"
              rows={newRows}
              onChange={setNewRows}
            />
            <div>
              <Button
                type="button"
                data-testid="create-connection"
                loading={create.isPending}
                disabled={selectedIntegration === ""}
                onClick={() => create.mutate()}
              >
                <Plug className="h-4 w-4" aria-hidden="true" />
                Save settings
              </Button>
            </div>
            {create.isError && <ErrorBanner error={create.error} />}
          </div>
        </Can>
      </CardContent>
    </Card>
  );
}
