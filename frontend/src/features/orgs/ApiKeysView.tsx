/**
 * `ApiKeysView`: org API-key management, gated behind `manage_api_keys`
 * (Req 4.5, 1.6).
 *
 * Binds ONLY to the shipped `/orgs/{org_id}/api-keys` contracts:
 *  - `GET  /orgs/{org_id}/api-keys`            — list key metadata (never secrets)
 *  - `POST /orgs/{org_id}/api-keys`            — issue a key (plaintext secret once)
 *  - `DELETE /orgs/{org_id}/api-keys/{key_id}` — revoke a key
 *
 * All management controls are wrapped in `<Can permission="manage_api_keys">`,
 * so when the Session Role lacks the permission they are absent from the DOM
 * (not merely disabled). A newly-created key's plaintext secret is shown
 * **once** with copy-to-clipboard + a toast and is never persisted in the
 * client. Revocation is confirmed via a destructive Radix dialog.
 *
 * Premium UX: cards with skeleton loaders, an explicit empty state, toasts,
 * responsive layout, WCAG AA.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import type { Role } from "../../auth/token";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
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

const MANAGE_API_KEYS: Permission = "manage_api_keys";
const ASSIGNABLE_ROLES: readonly Role[] = ["owner", "admin", "member", "viewer"];

interface ApiKeyMetadata {
  id: string;
  org_id: string;
  key_prefix: string;
  role: Role;
  created_at: string;
  revoked_at?: string | null;
}

interface CreateApiKeyResponse {
  api_key_id: string;
  key_prefix: string;
  role: Role;
  secret: string;
}

/** A one-shot copy-to-clipboard control for the freshly-issued secret. */
function CopySecret({ secret }: { secret: string }): JSX.Element {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard?.writeText(secret);
      setCopied(true);
      toast({ title: "Secret copied to clipboard", tone: "success" });
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast({ title: "Copy failed — select and copy manually", tone: "danger" });
    }
  }

  return (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      onClick={copy}
      data-testid="copy-secret"
      aria-label="Copy API key secret"
    >
      {copied ? (
        <Check className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Copy className="h-4 w-4" aria-hidden="true" />
      )}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

export function ApiKeysView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const permitted = role !== null && can(role, MANAGE_API_KEYS);

  const [newRole, setNewRole] = useState<Role>("viewer");
  const [createdSecret, setCreatedSecret] = useState<CreateApiKeyResponse | null>(null);

  const listKey = orgScopedKey(orgId, "api-keys");

  const query = useQuery<ApiKeyMetadata[], ClientError>({
    queryKey: listKey,
    // Only fetch when permitted and an org is active.
    enabled: permitted && orgId !== null,
    queryFn: () =>
      runRequest<ApiKeyMetadata[]>(() =>
        apiClient.GET("/orgs/{org_id}/api-keys", {
          params: { path: { org_id: orgId! } },
        }),
      ),
  });

  const createKey = useMutation<CreateApiKeyResponse, ClientError, Role>({
    mutationFn: (roleToGrant) =>
      runRequest<CreateApiKeyResponse>(() =>
        apiClient.POST("/orgs/{org_id}/api-keys", {
          params: { path: { org_id: orgId! } },
          body: { role: roleToGrant },
        }),
      ),
    onSuccess: (data) => {
      setCreatedSecret(data);
      toast({ title: "API key created", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  const revokeKey = useMutation<void, ClientError, string>({
    mutationFn: (keyId) =>
      runRequest<void>(() =>
        apiClient.DELETE("/orgs/{org_id}/api-keys/{key_id}", {
          params: { path: { org_id: orgId!, key_id: keyId } },
        }),
      ),
    onSuccess: () => {
      toast({ title: "API key revoked", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  if (!permitted) {
    return (
      <div data-testid="api-keys-view">
        <EmptyState
          title="API key management unavailable"
          message="Your role does not permit managing API keys for this organization."
          icon={<KeyRound className="h-8 w-8" />}
        />
      </div>
    );
  }

  const keys = query.data ?? [];

  return (
    <div className="flex flex-col gap-6" data-testid="api-keys-view">
      <PageHeader
        eyebrow="Administration"
        icon={KeyRound}
        title="API Keys"
        description="Issue and revoke org-scoped API keys. A key's secret is shown once at creation and never stored."
      />

      {/* The create form is two controls; on its own row above the list it left
          most of the viewport empty. Beside the list it reads as one screen. */}
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]">
      {/* The heading is what keeps the document order valid: the cards below use
          <h3> titles, so without an <h2> at this level the page would jump
          h1 -> h3 (axe `heading-order`, WCAG 1.3.1). */}
      <section className="flex flex-col gap-3" aria-labelledby="issue-key-heading">
      <h2
        id="issue-key-heading"
        className="text-sm font-semibold uppercase tracking-wide text-text-muted"
      >
        Create a key
      </h2>
      <Can permission={MANAGE_API_KEYS}>
        <Card>
          <CardHeader>
            <CardTitle>Key role</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-stretch gap-3">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="api-key-role" className="text-sm font-medium text-text">
                Role
              </label>
              <DropdownMenu>
                <DropdownMenuSelectTrigger
                  id="api-key-role"
                  data-testid="api-key-role-trigger"
                  className="w-40 capitalize"
                  value={newRole}
                />
                <DropdownMenuContent>
                  {ASSIGNABLE_ROLES.map((r) => (
                    <DropdownMenuItem
                      key={r}
                      data-testid={`api-key-role-${r}`}
                      onSelect={() => setNewRole(r)}
                    >
                      <span className="capitalize">{r}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <Button
              type="button"
              data-testid="create-api-key"
              loading={createKey.isPending}
              onClick={() => createKey.mutate(newRole)}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Create key
            </Button>
          </CardContent>
        </Card>
      </Can>

      {createKey.isError && <ErrorBanner error={createKey.error} />}

      {/* A key's secret is only ever shown once, so it stays in the left column
          next to the form that produced it rather than below a long list. */}
      {createdSecret && (
        <Card raised data-testid="created-secret">
          <CardHeader>
            <CardTitle>Copy your new key secret</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm text-text-muted">
              This secret is shown only once. Store it securely — you will not be
              able to view it again.
            </p>
            <div className="flex items-center gap-3">
              <code
                className="flex-1 truncate rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm"
                data-testid="secret-value"
              >
                {createdSecret.secret}
              </code>
              <CopySecret secret={createdSecret.secret} />
            </div>
          </CardContent>
        </Card>
      )}

      </section>

      <section className="flex min-w-0 flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
          Active keys
        </h2>

        {query.isError && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}

        {query.isLoading && (
          <div className="flex flex-col gap-2" data-testid="api-keys-loading">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}

        {!query.isLoading && !query.isError && keys.length === 0 && (
          <EmptyState
            title="No API keys yet"
            message="Create a key above to grant programmatic access scoped to this organization."
            icon={<KeyRound className="h-8 w-8" />}
          />
        )}

        {keys.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="api-keys-list">
            {keys.map((key) => (
              <li key={key.id}>
                <Card>
                  <CardContent className="flex flex-wrap items-center gap-3 py-4">
                    <KeyRound
                      className="h-4 w-4 shrink-0 text-text-muted"
                      aria-hidden="true"
                    />
                    <code className="text-sm text-text">{key.key_prefix}…</code>
                    <Badge tone="neutral" className="capitalize">
                      {key.role}
                    </Badge>
                    {key.revoked_at ? (
                      <Badge tone="danger">revoked</Badge>
                    ) : (
                      <Badge tone="success">active</Badge>
                    )}
                    <span className="ml-auto" />
                    <Can permission={MANAGE_API_KEYS}>
                      {!key.revoked_at && (
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button
                              type="button"
                              variant="danger"
                              size="sm"
                              data-testid={`revoke-api-key-${key.id}`}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                              Revoke
                            </Button>
                          </DialogTrigger>
                          <DialogContent
                            title="Revoke API key?"
                            description="This permanently disables the key. Any client using it will lose access immediately."
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
                                  data-testid={`confirm-revoke-${key.id}`}
                                  onClick={() => revokeKey.mutate(key.id)}
                                >
                                  Revoke key
                                </Button>
                              </DialogClose>
                            </div>
                          </DialogContent>
                        </Dialog>
                      )}
                    </Can>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        )}

        {revokeKey.isError && <ErrorBanner error={revokeKey.error} />}
      </section>
      </div>
    </div>
  );
}
