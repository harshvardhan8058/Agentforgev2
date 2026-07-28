/**
 * `PromptRegistryView`: the immutable versioned prompt registry / Prompt Studio
 * (`/prompts`, Req 12.1–12.7, 4.3).
 *
 * Lists `GET /prompts` template names; `GET /prompts/{name}/versions` (ascending)
 * version numbers; `GET /prompts/{name}?version=N` the resolved body/variables/
 * created-at. Creating a version (`POST /prompts`) is gated behind
 * `ingest_documents` via `<Can>` and shows the returned version number. The
 * `RenderPromptForm` renders a resolved version with required-variable blocking
 * (Property 12).
 *
 * Premium UX: the body editor and version diffing use **Monaco** via
 * `PromptStudio`, **lazy-loaded** (`React.lazy` + dynamic import, kept out of
 * the initial bundle) and **mocked in tests** so Monaco never loads under
 * Vitest.
 */
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCompare, Plus, SlidersHorizontal } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { RenderPromptForm } from "./RenderPromptForm";
import type { PromptStudioProps } from "./PromptStudio";

const PromptStudio = lazy(() => import("./PromptStudio"));

interface PromptVersion {
  id: string;
  name: string;
  version: number;
  body: string;
  variables: string[];
  created_at: string;
}

function StudioFallback(): JSX.Element {
  return <Skeleton className="h-72 w-full" data-testid="studio-skeleton" />;
}

function LazyStudio(props: PromptStudioProps): JSX.Element {
  return (
    <Suspense fallback={<StudioFallback />}>
      <PromptStudio {...props} />
    </Suspense>
  );
}

export function PromptRegistryView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const canCreate = role !== null && can(role, "ingest_documents");
  const promptNameRef = useRef<HTMLInputElement>(null);

  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [diffAgainst, setDiffAgainst] = useState<number | null>(null);

  // Create-version form state.
  const [newName, setNewName] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newVariables, setNewVariables] = useState("");

  const names = useQuery<string[], ClientError>({
    queryKey: orgScopedKey(orgId, "prompts"),
    queryFn: () => runRequest<string[]>(() => apiClient.GET("/prompts")),
  });

  const versions = useQuery<number[], ClientError>({
    enabled: selectedName !== null,
    queryKey: orgScopedKey(orgId, "prompt-versions", selectedName),
    queryFn: () =>
      runRequest<number[]>(() =>
        apiClient.GET("/prompts/{name}/versions", {
          params: { path: { name: selectedName as string } },
        }),
      ),
  });

  // Default to the latest version once the ascending list is available.
  useEffect(() => {
    if (versions.data && versions.data.length > 0 && selectedVersion === null) {
      setSelectedVersion(versions.data[versions.data.length - 1]);
    }
  }, [versions.data, selectedVersion]);

  const detail = useQuery<PromptVersion, ClientError>({
    enabled: selectedName !== null && selectedVersion !== null,
    queryKey: orgScopedKey(orgId, "prompt", selectedName, selectedVersion),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/prompts/{name}", {
          params: {
            path: { name: selectedName as string },
            query: { version: selectedVersion as number },
          },
        }),
      );
      return { ...data, variables: data.variables ?? [] };
    },
  });

  const diffDetail = useQuery<PromptVersion, ClientError>({
    enabled: selectedName !== null && diffAgainst !== null,
    queryKey: orgScopedKey(orgId, "prompt", selectedName, diffAgainst),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/prompts/{name}", {
          params: {
            path: { name: selectedName as string },
            query: { version: diffAgainst as number },
          },
        }),
      );
      return { ...data, variables: data.variables ?? [] };
    },
  });

  const create = useMutation<PromptVersion, ClientError, void>({
    mutationFn: async () => {
      const data = await runRequest(() =>
        apiClient.POST("/prompts", {
          body: {
            name: newName.trim(),
            body: newBody,
            variables: newVariables
              .split(",")
              .map((v) => v.trim())
              .filter((v) => v.length > 0),
          },
        }),
      );
      return { ...data, variables: data.variables ?? [] };
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, "prompts") });
      void queryClient.invalidateQueries({
        queryKey: orgScopedKey(orgId, "prompt-versions", created.name),
      });
    },
  });

  const selectName = (name: string): void => {
    setSelectedName(name);
    setSelectedVersion(null);
    setDiffAgainst(null);
  };

  const version = detail.data;

  return (
    <div className="flex flex-col gap-6" data-testid="prompts-view">
      <PageHeader
        eyebrow="Platform"
        icon={SlidersHorizontal}
        title="Prompts"
        description="Browse the immutable versioned registry, diff versions, and render prompts."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,16rem)_1fr]">
        {/* Left: template list + create form. */}
        <div className="flex flex-col gap-4">
          <Card data-testid="template-list-card">
            <CardHeader>
              <CardTitle className="text-base">Templates</CardTitle>
            </CardHeader>
            <CardContent>
              {names.isLoading && <Skeleton className="h-24 w-full" data-testid="templates-skeleton" />}
              {names.isError && <ErrorBanner error={names.error} onRetry={() => void names.refetch()} />}
              {names.data && names.data.length === 0 && (
                <EmptyState
                  title="No prompts yet"
                  message="Create your first versioned prompt template to get started."
                  action={
                    canCreate ? (
                      <Button
                        type="button"
                        data-testid="prompts-empty-cta"
                        onClick={() => promptNameRef.current?.focus()}
                      >
                        <Plus className="h-4 w-4" aria-hidden="true" />
                        New version
                      </Button>
                    ) : undefined
                  }
                />
              )}
              {names.data && names.data.length > 0 && (
                <ul className="flex flex-col gap-1" data-testid="template-list">
                  {names.data.map((name) => (
                    <li key={name}>
                      <button
                        type="button"
                        data-testid={`template-${name}`}
                        aria-pressed={selectedName === name}
                        onClick={() => selectName(name)}
                        className={
                          "w-full rounded-md px-3 py-1.5 text-left text-sm transition-colors " +
                          (selectedName === name
                            ? "bg-surface-raised text-text"
                            : "text-text-muted hover:bg-surface-raised hover:text-text")
                        }
                      >
                        {name}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Can permission="ingest_documents">
            <Card data-testid="create-version-card">
              <CardHeader>
                <CardTitle className="text-base">New version</CardTitle>
              </CardHeader>
              <CardContent>
                <form
                  className="flex flex-col gap-3"
                  data-testid="create-version-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (newName.trim().length === 0) return;
                    create.mutate();
                  }}
                >
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="prompt-name" className="text-sm font-medium text-text">
                      Name
                    </label>
                    <Input
                      id="prompt-name"
                      data-testid="prompt-name"
                      ref={promptNameRef}
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span className="text-sm font-medium text-text">Body</span>
                    <LazyStudio
                      value={newBody}
                      onChange={setNewBody}
                      data-testid="prompt-body-editor"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="prompt-variables" className="text-sm font-medium text-text">
                      Variables (comma-separated)
                    </label>
                    <Input
                      id="prompt-variables"
                      data-testid="prompt-variables"
                      value={newVariables}
                      onChange={(e) => setNewVariables(e.target.value)}
                    />
                  </div>
                  <div>
                    <Button type="submit" data-testid="create-version-submit" loading={create.isPending}>
                      Create version
                    </Button>
                  </div>
                  {create.isError && (
                    <div data-testid="create-version-error">
                      <ErrorBanner error={create.error} />
                    </div>
                  )}
                  {create.data && (
                    <p className="text-sm text-success" data-testid="create-version-result">
                      Created version {create.data.version}
                    </p>
                  )}
                </form>
              </CardContent>
            </Card>
          </Can>
        </div>

        {/* Right: version detail + studio + render form. */}
        <div className="flex flex-col gap-4">
          {selectedName === null && (
            <EmptyState
              title="Select a template"
              message="Choose a template on the left to view its versions."
              icon={<SlidersHorizontal className="h-8 w-8" />}
            />
          )}

          {selectedName !== null && (
            <Card data-testid="versions-card">
              <CardHeader>
                <CardTitle className="text-base">Versions of {selectedName}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {versions.isLoading && <Skeleton className="h-8 w-full" data-testid="versions-skeleton" />}
                {versions.isError && <ErrorBanner error={versions.error} />}
                {versions.data && (
                  <div className="flex flex-wrap gap-2" data-testid="version-list">
                    {versions.data.map((v) => (
                      <button
                        key={v}
                        type="button"
                        data-testid={`version-${v}`}
                        aria-pressed={selectedVersion === v}
                        onClick={() => {
                          setSelectedVersion(v);
                          setDiffAgainst(null);
                        }}
                      >
                        <Badge tone={selectedVersion === v ? "primary" : "neutral"}>v{v}</Badge>
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {detail.isLoading && <Skeleton className="h-40 w-full" data-testid="detail-skeleton" />}
          {detail.isError && (
            <div data-testid="detail-error">
              <ErrorBanner error={detail.error} />
            </div>
          )}

          {version && (
            <Card data-testid="version-detail-card">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">
                    {version.name} · v{version.version}
                  </CardTitle>
                  <span className="text-xs text-text-muted" data-testid="version-created-at">
                    {version.created_at}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {version.variables.length > 0 && (
                  <div className="flex flex-wrap gap-1.5" data-testid="version-variables">
                    {version.variables.map((v) => (
                      <Badge key={v} tone="info" data-testid={`version-variable-${v}`}>
                        {v}
                      </Badge>
                    ))}
                  </div>
                )}

                {/* Body / diff studio. */}
                {diffAgainst !== null && diffDetail.data ? (
                  <LazyStudio
                    mode="diff"
                    original={diffDetail.data.body}
                    value={version.body}
                    data-testid="version-diff-editor"
                  />
                ) : (
                  <LazyStudio
                    value={version.body}
                    readOnly
                    data-testid="version-body-editor"
                  />
                )}

                {versions.data && versions.data.length > 1 && (
                  <div className="flex flex-wrap items-center gap-2" data-testid="diff-controls">
                    <span className="text-xs text-text-muted">
                      <GitCompare className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
                      Compare with
                    </span>
                    {versions.data
                      .filter((v) => v !== version.version)
                      .map((v) => (
                        <button key={v} type="button" data-testid={`diff-with-${v}`} onClick={() => setDiffAgainst(v)}>
                          <Badge tone={diffAgainst === v ? "primary" : "neutral"}>v{v}</Badge>
                        </button>
                      ))}
                  </div>
                )}

                <RenderPromptForm
                  name={version.name}
                  version={version.version}
                  variables={version.variables}
                />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
