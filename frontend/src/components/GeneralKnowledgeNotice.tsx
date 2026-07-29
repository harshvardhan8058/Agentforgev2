/**
 * `GeneralKnowledgeNotice`: labels an answer that did NOT come from the corpus.
 *
 * When a deployment opts in to ungrounded answers, `/query` may answer a question the
 * corpus does not cover using the model's own knowledge. Such answers come back with
 * `grounded: false` and zero citations, which is honest but easy to miss. This states
 * it outright, so a model-knowledge answer is never mistaken for a document-backed,
 * verifiable one.
 */
import type { JSX } from "react";
import { Globe } from "lucide-react";

/**
 * The exact refusal text the backend returns when ungrounded answers are disabled
 * (`NO_GROUNDING_MESSAGE` in `rag/service.py`). That case is a refusal, not a
 * general-knowledge answer, so the notice must not claim otherwise.
 */
export const NO_GROUNDING_MESSAGE =
  "No grounding information is available to answer this question.";

/** True when this is a real model-knowledge answer rather than a refusal. */
export function isGeneralKnowledgeAnswer(grounded: boolean, answer: string): boolean {
  return !grounded && answer.trim() !== NO_GROUNDING_MESSAGE;
}

export function GeneralKnowledgeNotice(): JSX.Element {
  return (
    <div
      data-testid="general-knowledge-notice"
      className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/15 px-3 py-2 text-xs text-text-muted"
    >
      <Globe className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
      <span>
        <span className="font-medium text-text">Not from your documents.</span> Nothing in
        your corpus matched this question, so this was answered from the model&apos;s general
        knowledge — there are no citations to verify it against. Upload a relevant document
        to get a grounded, cited answer.
      </span>
    </div>
  );
}
