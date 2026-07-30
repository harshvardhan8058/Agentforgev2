/**
 * `PromptStudio`: the prompt body editor and version diff viewer.
 *
 * Previously this wrapped Monaco via `@monaco-editor/react`, which fetches the
 * editor from a CDN on first render. A self-hosted deployment has no route to
 * that CDN, so the component sat on "Loading…" indefinitely: the prompt body
 * could not be typed, versions could not be compared, and the placeholder's
 * fixed height distorted the surrounding grid. A ~70 MB dependency and an
 * outbound request for a plain-text field was the wrong trade in the first
 * place — and it was the only reason the build carried a `dompurify` override,
 * since Monaco pinned a vulnerable 3.2.x.
 *
 * So editing is a real `<textarea>` with a synchronised line-number gutter, and
 * diffing renders the pure `diffLines` walk. Both work offline, need no worker,
 * and add nothing to the bundle. The textarea also brings behaviour Monaco was
 * being used to buy: native spellcheck-off, native undo, and — the reason the
 * field exists — the OS clipboard and screen-reader support of a normal form
 * control.
 *
 * Still default-exported so the existing import site (and the test double that
 * mocks this module) keep working unchanged.
 */
import type { JSX } from "react";
import { useLayoutEffect, useMemo, useRef } from "react";
import type { ChangeEvent, KeyboardEvent, UIEvent } from "react";

import { cn } from "../../lib/cn";
import { diffLines, diffStats, referencedVariables } from "./lineDiff";

export interface PromptStudioProps {
  /** The current (modified) body value. */
  value: string;
  /** When in diff mode, the original body to compare against. */
  original?: string;
  /** `edit` shows a single editor; `diff` shows the version comparison. */
  mode?: "edit" | "diff";
  /** Change handler for edit mode. */
  onChange?: (next: string) => void;
  readOnly?: boolean;
  "data-testid"?: string;
}

/** Two spaces per indent: prompt bodies are prose, not code. */
const INDENT = "  ";

/** A gutter of 1..count line numbers, kept in scroll sync with the content. */
function Gutter({
  count,
  scrollRef,
}: {
  count: number;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}): JSX.Element {
  return (
    <div
      ref={scrollRef}
      aria-hidden="true"
      className="select-none overflow-hidden border-r border-border bg-bg-subtle px-2 py-2 text-right font-mono text-xs leading-[1.6] text-text-subtle"
    >
      {Array.from({ length: Math.max(count, 1) }, (_, i) => (
        <div key={i + 1}>{i + 1}</div>
      ))}
    </div>
  );
}

/** The variables the body references, so the declared list can be kept in step. */
function VariableHints({ body }: { body: string }): JSX.Element | null {
  const variables = useMemo(() => referencedVariables(body), [body]);
  if (variables.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 py-2"
      data-testid="prompt-body-variables"
    >
      <span className="text-xs text-text-subtle">Referenced:</span>
      {variables.map((name) => (
        <code
          key={name}
          className="rounded bg-primary-subtle px-1.5 py-0.5 font-mono text-xs text-primary"
        >
          {name}
        </code>
      ))}
    </div>
  );
}

function Editor({
  value,
  onChange,
  readOnly,
  testId,
}: {
  value: string;
  onChange?: (next: string) => void;
  readOnly: boolean;
  testId: string;
}): JSX.Element {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const lineCount = value.length === 0 ? 1 : value.split("\n").length;

  // Keep the gutter aligned with the textarea's own scrolling.
  function syncScroll(event: UIEvent<HTMLTextAreaElement>): void {
    if (gutterRef.current) {
      gutterRef.current.scrollTop = event.currentTarget.scrollTop;
    }
  }

  useLayoutEffect(() => {
    if (gutterRef.current && textareaRef.current) {
      gutterRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  }, [value]);

  // Tab inserts an indent instead of leaving the field. Shift+Tab and Escape
  // still move focus, so the field is never a keyboard trap (WCAG 2.1.2).
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Tab" || event.shiftKey || readOnly) return;
    event.preventDefault();
    const field = event.currentTarget;
    const { selectionStart, selectionEnd } = field;
    const next =
      value.slice(0, selectionStart) + INDENT + value.slice(selectionEnd);
    onChange?.(next);
    // Restore the caret after React re-renders with the new value.
    requestAnimationFrame(() => {
      field.selectionStart = selectionStart + INDENT.length;
      field.selectionEnd = selectionStart + INDENT.length;
    });
  }

  return (
    <div
      className="overflow-hidden rounded-lg border border-border bg-surface"
      data-testid={testId}
      data-mode="edit"
    >
      <div className="grid grid-cols-[auto_1fr]">
        <Gutter count={lineCount} scrollRef={gutterRef} />
        <textarea
          ref={textareaRef}
          value={value}
          readOnly={readOnly}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange?.(e.target.value)}
          onKeyDown={onKeyDown}
          onScroll={syncScroll}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          aria-label="Prompt body"
          placeholder={
            readOnly
              ? undefined
              : "Write the prompt body. Reference variables as {{name}}."
          }
          className={cn(
            "h-64 w-full resize-y bg-transparent px-3 py-2 font-mono text-[13px] leading-[1.6] text-text",
            "placeholder:text-text-subtle focus-visible:outline-none",
            readOnly && "cursor-default text-text-muted",
          )}
        />
      </div>
      <VariableHints body={value} />
    </div>
  );
}

const KIND_STYLE: Record<"equal" | "add" | "remove", string> = {
  equal: "text-text-muted",
  add: "bg-success/10 text-text",
  remove: "bg-danger/10 text-text",
};

const KIND_MARK: Record<"equal" | "add" | "remove", string> = {
  equal: " ",
  add: "+",
  remove: "-",
};

function Diff({
  original,
  value,
  testId,
}: {
  original: string;
  value: string;
  testId: string;
}): JSX.Element {
  const lines = useMemo(() => diffLines(original, value), [original, value]);
  const stats = useMemo(() => diffStats(lines), [lines]);

  return (
    <div
      className="overflow-hidden rounded-lg border border-border bg-surface"
      data-testid={testId}
      data-mode="diff"
    >
      <div
        className="flex flex-wrap items-center gap-3 border-b border-border bg-bg-subtle px-3 py-2 text-xs"
        data-testid="diff-summary"
      >
        <span className="text-success">+{stats.added} added</span>
        <span className="text-danger">-{stats.removed} removed</span>
        <span className="text-text-subtle">{stats.unchanged} unchanged</span>
      </div>

      {lines.length === 0 ? (
        <p className="px-3 py-4 text-sm text-text-muted" data-testid="diff-empty">
          Both versions are empty.
        </p>
      ) : (
        <ol className="max-h-72 overflow-auto py-1 font-mono text-[13px] leading-[1.6]">
          {lines.map((line, index) => (
            <li
              key={`${line.kind}-${index}`}
              data-diff-kind={line.kind}
              className={cn("grid grid-cols-[3rem_3rem_1rem_1fr] gap-2", KIND_STYLE[line.kind])}
            >
              <span aria-hidden="true" className="px-1 text-right text-text-subtle">
                {line.leftNumber ?? ""}
              </span>
              <span aria-hidden="true" className="px-1 text-right text-text-subtle">
                {line.rightNumber ?? ""}
              </span>
              <span aria-hidden="true" className="text-center">
                {KIND_MARK[line.kind]}
              </span>
              {/* Preserve leading whitespace; an empty line still needs height. */}
              <span className="whitespace-pre-wrap break-words pr-3">
                {line.text.length === 0 ? "\u00a0" : line.text}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
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
    return <Diff original={original} value={value} testId={testId} />;
  }
  return (
    <Editor value={value} onChange={onChange} readOnly={readOnly} testId={testId} />
  );
}
