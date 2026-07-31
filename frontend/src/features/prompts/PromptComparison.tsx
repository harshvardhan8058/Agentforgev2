/**
 * `PromptComparison`: render two versions of a prompt from one set of inputs.
 *
 * The registry could show a version's body and diff two bodies, but a prompt's body is
 * not what you are actually choosing between — the *rendered result* is. With variables
 * substituted, a wording change can turn out to matter far less (or far more) than the
 * body diff suggests. Judging that previously meant rendering one version, copying the
 * output somewhere, switching version, re-entering every variable identically, and
 * comparing by eye.
 *
 * So: pick two versions, supply the variables once, and see both results side by side
 * plus a line diff of them. Variables are the **union** of what the two versions declare,
 * because versions are independent and may not declare the same set; a value is shared
 * across both renders, which is the whole point — the inputs are held constant so the
 * only difference is the prompt.
 *
 * Built entirely on the existing `POST /prompts/{name}/render` (called once per version)
 * and the existing LCS diff, so it adds no API surface.
 */
import type { JSX } from "react";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Columns2, GitCompare } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { Input } from "../../components/ui/Input";
import { Skeleton } from "../../components/ui/Skeleton";
import { suggestVariableValue } from "../../lib/examples";
import PromptStudio from "./PromptStudio";
import { missingVariables } from "./requiredVariables";

interface PromptVersionDetail {
  name: string;
  version: number;
  body: string;
  variables?: string[];
}

interface RenderResult {
  name: string;
  version: number;
  rendered: string;
}

/** Fetch one version's detail so its declared variables are known. */
function useVersionDetail(name: string, version: number | null) {
  const { orgId } = useSession();
  return useQuery<PromptVersionDetail, ClientError>({
    enabled: version !== null,
    queryKey: orgScopedKey(orgId, "prompt", name, version),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/prompts/{name}", {
          params: { path: { name }, query: { version: version as number } },
        }),
      );
      return { ...data, variables: data.variables ?? [] };
    },
  });
}

/** A labelled version picker. */
function VersionPicker({
  label,
  value,
  versions,
  onChange,
  testId,
}: {
  label: string;
  value: number | null;
  versions: readonly number[];
  onChange: (version: number) => void;
  testId: string;
}): JSX.Element {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium uppercase tracking-wide text-text-subtle">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5" data-testid={testId}>
        {versions.map((version) => (
          <button
            key={version}
            type="button"
            aria-pressed={value === version}
            data-testid={`${testId}-v${version}`}
            onClick={() => onChange(version)}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            <Badge tone={value === version ? "primary" : "neutral"}>v{version}</Badge>
          </button>
        ))}
      </div>
    </div>
  );
}

export function PromptComparison({
  name,
  versions,
}: {
  name: string;
  /** Available version numbers, ascending. */
  versions: readonly number[];
}): JSX.Element | null {
  // Nothing to compare against a single version.
  if (versions.length < 2) return null;

  return <Comparison name={name} versions={versions} />;
}

/**
 * Split from the guard above so the hooks below are only ever mounted when there are
 * two versions to compare — a conditional `return` before hooks would violate the rules
 * of hooks.
 */
function Comparison({
  name,
  versions,
}: {
  name: string;
  versions: readonly number[];
}): JSX.Element {
  // Default to the newest against the one before it: the comparison an operator who has
  // just added a version almost always wants.
  const [versionA, setVersionA] = useState<number>(versions[versions.length - 2]);
  const [versionB, setVersionB] = useState<number>(versions[versions.length - 1]);
  const [values, setValues] = useState<Record<string, string>>({});

  const detailA = useVersionDetail(name, versionA);
  const detailB = useVersionDetail(name, versionB);

  // The union, in a stable order: two versions are independent and may declare
  // different variables, and a value must be supplied for every variable either side
  // needs or that render fails.
  const variables = useMemo(() => {
    const merged: string[] = [];
    for (const variable of [
      ...(detailA.data?.variables ?? []),
      ...(detailB.data?.variables ?? []),
    ]) {
      if (!merged.includes(variable)) merged.push(variable);
    }
    return merged;
  }, [detailA.data?.variables, detailB.data?.variables]);

  const missing = missingVariables(variables, values);
  const suggestible = variables.filter((v) => suggestVariableValue(v) !== null);
  const loadingDetails = detailA.isLoading || detailB.isLoading;
  const sameVersion = versionA === versionB;

  const compare = useMutation<
    { a: RenderResult; b: RenderResult },
    ClientError,
    void
  >({
    mutationFn: async () => {
      const render = (version: number) =>
        runRequest<RenderResult>(() =>
          apiClient.POST("/prompts/{name}/render", {
            params: { path: { name } },
            body: { variables: values, version },
          }),
        );
      // In parallel: the two renders are independent, and holding the inputs constant is
      // what makes the outputs comparable.
      const [a, b] = await Promise.all([render(versionA), render(versionB)]);
      return { a, b };
    },
  });

  const result = compare.data;

  return (
    <Card data-testid="prompt-comparison-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Columns2 className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Compare versions
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm leading-relaxed text-text-muted">
          Render two versions from the same inputs. A body diff shows what changed in the
          prompt; this shows what it changes in the result.
        </p>

        <div className="grid grid-cols-2 gap-4">
          <VersionPicker
            label="Version A"
            value={versionA}
            versions={versions}
            onChange={setVersionA}
            testId="compare-version-a"
          />
          <VersionPicker
            label="Version B"
            value={versionB}
            versions={versions}
            onChange={setVersionB}
            testId="compare-version-b"
          />
        </div>

        {sameVersion && (
          <p className="text-xs text-warning" data-testid="compare-same-version">
            Pick two different versions to see a difference.
          </p>
        )}

        {loadingDetails && (
          <Skeleton className="h-16 w-full" data-testid="compare-details-skeleton" />
        )}

        {(detailA.isError || detailB.isError) && (
          <ErrorBanner error={(detailA.error ?? detailB.error) as ClientError} />
        )}

        {!loadingDetails && variables.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-text">
                Variables used by both renders
              </span>
              {suggestible.length > 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  data-testid="compare-fill-example"
                  onClick={() =>
                    setValues((prev) => {
                      const filled = { ...prev };
                      for (const variable of suggestible) {
                        filled[variable] = suggestVariableValue(variable) as string;
                      }
                      return filled;
                    })
                  }
                >
                  Fill example values
                </Button>
              )}
            </div>

            {variables.map((variable) => (
              <div key={variable} className="flex flex-col gap-1.5">
                <label
                  htmlFor={`compare-var-${variable}`}
                  className="text-sm font-medium text-text"
                >
                  {variable}
                </label>
                <Input
                  id={`compare-var-${variable}`}
                  data-testid={`compare-var-${variable}`}
                  value={values[variable] ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [variable]: e.target.value }))
                  }
                />
                {suggestVariableValue(variable) !== null && (
                  <ExampleChips
                    label="Example"
                    examples={[
                      {
                        label: "Use example",
                        value: suggestVariableValue(variable) as string,
                      },
                    ]}
                    onPick={(value) =>
                      setValues((prev) => ({ ...prev, [variable]: value }))
                    }
                    testId={`compare-var-${variable}-examples`}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {!loadingDetails && variables.length === 0 && (
          <p className="text-sm text-text-muted" data-testid="compare-no-variables">
            Neither version declares variables, so both render as written.
          </p>
        )}

        {missing.length > 0 && (
          <p className="text-sm text-warning" data-testid="compare-missing-prompt">
            Please provide a value for: {missing.join(", ")}
          </p>
        )}

        <div>
          <Button
            type="button"
            data-testid="compare-submit"
            // Mirrors the render form: never issue a request that cannot succeed
            // (Property 12), and a version compared with itself is not a comparison.
            disabled={missing.length > 0 || sameVersion || loadingDetails}
            loading={compare.isPending}
            onClick={() => compare.mutate()}
          >
            <GitCompare className="h-4 w-4" aria-hidden="true" />
            Compare
          </Button>
        </div>

        {compare.isError && (
          <div data-testid="compare-error">
            <ErrorBanner error={compare.error} />
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-4" data-testid="compare-result">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {[result.a, result.b].map((side, index) => (
                <div
                  key={side.version}
                  className="flex min-w-0 flex-col gap-1.5"
                  data-testid={`compare-output-${index === 0 ? "a" : "b"}`}
                >
                  <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                    {index === 0 ? "A" : "B"} · v{side.version}
                  </span>
                  <pre className="whitespace-pre-wrap break-words rounded-lg border border-border bg-bg-subtle p-3 font-mono text-sm text-text">
                    {side.rendered}
                  </pre>
                </div>
              ))}
            </div>

            {result.a.rendered === result.b.rendered ? (
              <p
                className="text-sm text-text-muted"
                data-testid="compare-identical"
              >
                Both versions render identically for these inputs — the wording that
                differs between them does not affect this case.
              </p>
            ) : (
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
                  Difference (A → B)
                </span>
                {/* Reuses the same offline LCS diff the body comparison uses. */}
                <PromptStudio
                  mode="diff"
                  original={result.a.rendered}
                  value={result.b.rendered}
                  data-testid="compare-diff"
                />
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
