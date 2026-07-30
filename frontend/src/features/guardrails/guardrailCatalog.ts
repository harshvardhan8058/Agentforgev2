/**
 * Human descriptions for the built-in guardrails.
 *
 * `GET /guardrails/config` returns each guardrail's stable `name` plus a `kind`
 * that is literally `type(guardrail).__name__` — a Python class name such as
 * `Non_Empty_Guardrail`. That was being rendered as a badge, so the page
 * displayed internal identifiers and still never said what any guardrail
 * actually does. The `kind` remains useful for support, but it belongs in a
 * tooltip, not as the headline.
 *
 * Descriptions are keyed on the stable `name`, which is part of the API
 * contract, rather than on the class name, which is not. An unrecognised
 * guardrail gets its name humanised and **no description** — inventing a
 * behaviour for a guardrail this build does not know about would be worse than
 * saying nothing, since an operator would rely on it.
 */

export interface GuardrailDescription {
  /** Display label. */
  readonly label: string;
  /** What the guardrail enforces, or null when unknown to this build. */
  readonly description: string | null;
}

/**
 * The guardrails the platform ships, keyed by the `name` each reports.
 *
 * Wording deliberately avoids quoting configured values (the max length, the
 * blocklist terms) because the config endpoint does not return them, so a
 * concrete number here could contradict the deployment.
 */
const BUILT_IN: Record<string, GuardrailDescription> = {
  non_empty: {
    label: "Non-empty content",
    description: "Blocks content that is empty or only whitespace.",
  },
  max_length: {
    label: "Maximum length",
    description:
      "Blocks content longer than the configured character limit for this deployment.",
  },
  blocklist: {
    label: "Term blocklist",
    description:
      "Blocks content containing any configured term, matched case-insensitively. No terms are configured unless the deployment supplies them.",
  },
};

/** Turn `some_guardrail_name` into `Some guardrail name`. */
function humanise(name: string): string {
  const spaced = name.replace(/[_-]+/g, " ").trim();
  if (spaced.length === 0) return name;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Describe a guardrail by its stable API `name`. */
export function describeGuardrail(name: string): GuardrailDescription {
  return BUILT_IN[name] ?? { label: humanise(name), description: null };
}
