/**
 * `RenderPromptForm`: renders a resolved Prompt_Version with supplied variable
 * values (Req 12.5, 12.6, 12.7; Property 12).
 *
 * Submission is blocked (no `POST /prompts/{name}/render` is issued) while any
 * declared variable is unsupplied; the form prompts for exactly the missing set
 * (`missingVariables`, Property 12). On success it shows the rendered string;
 * on `400 missing_variable` it surfaces `details.missing` via `ErrorBanner`.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { suggestVariableValue } from "../../lib/examples";
import { missingVariables } from "./requiredVariables";

interface RenderResult {
  name: string;
  version: number;
  rendered: string;
}

export function RenderPromptForm({
  name,
  version,
  variables,
}: {
  name: string;
  version: number;
  variables: string[];
}): JSX.Element {
  const [values, setValues] = useState<Record<string, string>>({});

  const missing = missingVariables(variables, values);
  const blocked = missing.length > 0;
  // Only variables a suggestion is actually known for; guessing a value for an
  // unrecognized name would put misleading content in the render preview.
  const suggestibleVariables = variables.filter(
    (variable) => suggestVariableValue(variable) !== null,
  );

  const render = useMutation<RenderResult, ClientError, void>({
    mutationFn: () =>
      runRequest<RenderResult>(() =>
        apiClient.POST("/prompts/{name}/render", {
          params: { path: { name } },
          body: { variables: values, version },
        }),
      ),
  });

  const result = render.data;
  const missingFromServer =
    render.error && Array.isArray(render.error.details.missing)
      ? (render.error.details.missing as unknown[]).filter(
          (m): m is string => typeof m === "string",
        )
      : [];

  return (
    <form
      className="flex flex-col gap-3"
      data-testid="render-form"
      onSubmit={(e) => {
        e.preventDefault();
        // Property 12: never issue the request while a declared var is missing.
        if (blocked) return;
        render.mutate();
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-text">Render preview</h3>
        {/* Rendering is blocked until every declared variable has a value, so
            with several variables the fastest path to seeing a result was
            typing filler into each one. This fills only the variables a
            suggestion is known for, leaving the rest to the Operator. */}
        {suggestibleVariables.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="render-fill-example"
            onClick={() =>
              setValues((prev) => {
                const filled = { ...prev };
                for (const variable of suggestibleVariables) {
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

      {variables.length === 0 && (
        <p className="text-sm text-text-muted" data-testid="render-no-variables">
          This version declares no variables.
        </p>
      )}

      {variables.map((variable) => (
        <div key={variable} className="flex flex-col gap-1.5">
          <label
            htmlFor={`render-var-${variable}`}
            className="text-sm font-medium text-text"
          >
            {variable}
          </label>
          <Input
            id={`render-var-${variable}`}
            data-testid={`render-var-${variable}`}
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
              testId={`render-var-${variable}-examples`}
            />
          )}
        </div>
      ))}

      {blocked && (
        <p className="text-sm text-warning" data-testid="render-missing-prompt">
          Please provide a value for: {missing.join(", ")}
        </p>
      )}

      <div>
        <Button
          type="submit"
          data-testid="render-submit"
          disabled={blocked}
          loading={render.isPending}
        >
          <Play className="h-4 w-4" aria-hidden="true" />
          Render
        </Button>
      </div>

      {render.isError && (
        <div data-testid="render-error">
          <ErrorBanner error={render.error} />
          {missingFromServer.length > 0 && (
            <p className="mt-1 text-sm text-danger" data-testid="render-server-missing">
              Missing: {missingFromServer.join(", ")}
            </p>
          )}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-1" data-testid="render-result">
          <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Rendered (v{result.version})
          </span>
          <pre
            className="whitespace-pre-wrap rounded-lg border border-border bg-bg-subtle p-3 font-mono text-sm text-text"
            data-testid="render-output"
          >
            {result.rendered}
          </pre>
        </div>
      )}
    </form>
  );
}
