/**
 * `PromptStudio`: the Monaco-backed prompt editor (Premium UX §3, "Prompt
 * Studio").
 *
 * Provides variable-aware editing of a prompt body and side-by-side **version
 * diffing** (Monaco `DiffEditor`) across immutable versions. This module is
 * **lazy-loaded** via `React.lazy` + dynamic import (kept out of the initial
 * bundle) and **mocked in tests** with a lightweight textarea-like stub, so
 * Monaco is never loaded under Vitest and the suite stays keyless and
 * deterministic.
 *
 * Default-exported for `React.lazy`.
 */
import type { JSX } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";

export interface PromptStudioProps {
  /** The current (modified) body value. */
  value: string;
  /** When in diff mode, the original body to compare against. */
  original?: string;
  /** `edit` shows a single editor; `diff` shows a side-by-side comparison. */
  mode?: "edit" | "diff";
  /** Change handler for edit mode. */
  onChange?: (next: string) => void;
  readOnly?: boolean;
  "data-testid"?: string;
}

export default function PromptStudio({
  value,
  original = "",
  mode = "edit",
  onChange,
  readOnly = false,
  "data-testid": testId = "prompt-studio",
}: PromptStudioProps): JSX.Element {
  if (mode === "diff") {
    return (
      <div className="h-72 overflow-hidden rounded-lg border border-border" data-testid={testId}>
        <DiffEditor
          original={original}
          modified={value}
          language="markdown"
          theme="vs-dark"
          options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false } }}
        />
      </div>
    );
  }

  return (
    <div className="h-72 overflow-hidden rounded-lg border border-border" data-testid={testId}>
      <Editor
        value={value}
        language="markdown"
        theme="vs-dark"
        onChange={(next) => onChange?.(next ?? "")}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 13,
        }}
      />
    </div>
  );
}
