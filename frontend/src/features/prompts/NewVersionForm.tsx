/**
 * `NewVersionForm`: creates a new immutable prompt version (`POST /prompts`).
 *
 * Extracted from `PromptRegistryView` so it can sit in the wide column. It was
 * previously in the 16rem template-list column, which meant the body editor —
 * the one field that needs room — was the narrowest thing on the page, and the
 * page rendered two empty states side by side before any prompt existed.
 *
 * The name input's ref is owned by the parent so the template list's empty-state
 * call to action can focus this form's first field.
 */
import type { JSX, RefObject } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { PROMPT_STARTERS } from "../../lib/examples";
import PromptStudio from "./PromptStudio";
import { referencedVariables } from "./lineDiff";

interface PromptVersion {
  id: string;
  name: string;
  version: number;
  body: string;
  variables: string[];
  created_at: string;
}

export function NewVersionForm({
  nameRef,
}: {
  nameRef?: RefObject<HTMLInputElement | null>;
}): JSX.Element {
  const { orgId } = useSession();
  const queryClient = useQueryClient();

  const [newName, setNewName] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newVariables, setNewVariables] = useState("");

  const declared = newVariables
    .split(",")
    .map((v) => v.trim())
    .filter((v) => v.length > 0);
  // Rendering a version fails if a variable the body references is not declared,
  // and nothing in the UI used to reveal that mismatch until the render failed.
  const undeclared = referencedVariables(newBody).filter(
    (name) => !declared.includes(name),
  );

  const create = useMutation<PromptVersion, ClientError, void>({
    mutationFn: async () => {
      const data = await runRequest(() =>
        apiClient.POST("/prompts", {
          body: { name: newName.trim(), body: newBody, variables: declared },
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

  return (
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
          {/* A prompt is three coupled fields — name, body and the variables the
              body references — so a starter fills all three at once. Filling only
              the name would leave a form that still needs a body written by hand. */}
          <ExampleChips
            label="Start from"
            examples={PROMPT_STARTERS.map((s) => ({ label: s.label, value: s.name }))}
            onPick={(name) => {
              const starter = PROMPT_STARTERS.find((s) => s.name === name);
              if (!starter) return;
              setNewName(starter.name);
              setNewBody(starter.body);
              setNewVariables(starter.variables);
            }}
            testId="prompt-starters"
          />

          <div className="flex flex-col gap-1.5">
            <label htmlFor="prompt-name" className="text-sm font-medium text-text">
              Name
            </label>
            <Input
              id="prompt-name"
              data-testid="prompt-name"
              ref={nameRef}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="grounded-answer"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-text">Body</span>
            <PromptStudio
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
              placeholder="context, question"
            />
            {undeclared.length > 0 && (
              <p className="text-xs text-warning" data-testid="prompt-undeclared-variables">
                The body references {undeclared.join(", ")} — add{" "}
                {undeclared.length === 1 ? "it" : "them"} above, or rendering this
                version will fail.
              </p>
            )}
          </div>

          <div>
            <Button
              type="submit"
              data-testid="create-version-submit"
              loading={create.isPending}
            >
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
  );
}
