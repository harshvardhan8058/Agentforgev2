/**
 * One-click preset examples for every input surface in the console.
 *
 * Kept in a single module so the demo story is coherent rather than each view
 * inventing its own placeholder: the sample documents below are what the query,
 * agent and multi-agent examples actually ask about, so loading the samples and
 * then picking any example produces a *grounded, cited* answer instead of "no
 * relevant context found".
 *
 * Every preset here is checked against what the backend really accepts:
 * evaluator names are the three registered deterministic evaluators
 * (`exact_match`, `contains`, `heuristic`), and the guardrail examples exercise
 * the guardrails that are active by default. Offering a preset that fails would
 * be worse than offering none.
 */

/** A preset with a short chip label distinct from the value it inserts. */
export interface Example {
  /** Short, scannable chip text. */
  readonly label: string;
  /** The full value written into the field. */
  readonly value: string;
}

// --- Retrieval / agent tasks -------------------------------------------------
// Phrased to match the sample corpus below so the answers come back cited.

export const QUERY_EXAMPLES: readonly Example[] = [
  {
    label: "Onboarding equipment",
    value: "What equipment does the onboarding policy provide on day one?",
  },
  {
    label: "Probation period",
    value: "How long is the probation period and who reviews it?",
  },
  {
    label: "Q3 incident cause",
    value: "What was the root cause of the Q3 checkout outage?",
  },
];

export const AGENT_EXAMPLES: readonly Example[] = [
  {
    label: "Summarize the incident",
    value: "Summarize the Q3 checkout outage: impact, root cause, and follow-up actions.",
  },
  {
    label: "Onboarding checklist",
    value: "List the onboarding steps for a new engineer from the policy.",
  },
  {
    label: "Launch risks",
    value: "What risks does the product launch plan call out, and how are they mitigated?",
  },
];

export const MULTI_AGENT_EXAMPLES: readonly Example[] = [
  {
    label: "Q3 incident briefing",
    value: "Draft a briefing on the Q3 checkout outage with sources.",
  },
  {
    label: "Launch plan outline",
    value: "Research and outline the product launch plan, with owners per phase.",
  },
  {
    label: "Compare & recommend",
    value:
      "Compare the two rollback approaches in the incident report and recommend one.",
  },
];

// --- Guardrails --------------------------------------------------------------
// The default pipeline is non_empty -> max_length -> blocklist. Only the first
// two are deterministic out of the box: the blocklist is empty unless
// GUARDRAIL_BLOCKLIST_JSON is configured, so no preset here claims to trip it.

/** Comfortably over the 8000-char default `guardrail_max_input_chars`. */
const OVERLONG_INPUT = "This sentence pads the input past the length limit. ".repeat(
  170,
);

export const GUARDRAIL_EXAMPLES: readonly Example[] = [
  {
    label: "Allowed",
    value: "Summarize our onboarding policy for a new engineer.",
  },
  // Whitespace-only rather than truly empty, so the field is non-blank in the UI
  // while still tripping the non_empty guardrail server-side.
  { label: "Blocked — empty", value: "   " },
  { label: "Blocked — too long", value: OVERLONG_INPUT },
];

// --- Evaluations -------------------------------------------------------------

export const DATASET_NAME_EXAMPLES: readonly Example[] = [
  { label: "Onboarding QA", value: "Onboarding policy QA" },
  { label: "Incident QA", value: "Q3 incident questions" },
  { label: "Regression set", value: "Grounded-answer regression set" },
];

/** The three evaluators registered by the composition root. */
export const EVALUATOR_EXAMPLES: readonly Example[] = [
  { label: "All three", value: "exact_match, contains, heuristic" },
  { label: "exact_match", value: "exact_match" },
  { label: "contains", value: "contains" },
  { label: "heuristic", value: "heuristic" },
];

// --- Prompt registry ---------------------------------------------------------

/** A starter that fills the name, body and variables of a new prompt version. */
export interface PromptStarter {
  readonly label: string;
  readonly name: string;
  readonly body: string;
  /** Comma-separated, matching the form's input format. */
  readonly variables: string;
}

export const PROMPT_STARTERS: readonly PromptStarter[] = [
  {
    label: "Grounded answer",
    name: "grounded-answer",
    body: [
      "You are a careful analyst. Answer the question using ONLY the context below.",
      "Cite each claim with the bracketed source number it came from.",
      "If the context does not support an answer, say so plainly.",
      "",
      "Context:",
      "{{context}}",
      "",
      "Question:",
      "{{question}}",
    ].join("\n"),
    variables: "context, question",
  },
  {
    label: "Incident briefing",
    name: "incident-briefing",
    body: [
      "Write a briefing on the incident below for a {{audience}} audience.",
      "Cover impact, root cause, and follow-up actions in that order.",
      "Keep it under {{word_limit}} words.",
      "",
      "Incident notes:",
      "{{notes}}",
    ].join("\n"),
    variables: "audience, word_limit, notes",
  },
  {
    label: "Summarize",
    name: "summarize",
    body: [
      "Summarize the following text in {{sentence_count}} sentences.",
      "Preserve every figure and date exactly as written.",
      "",
      "{{text}}",
    ].join("\n"),
    variables: "sentence_count, text",
  },
];

/**
 * Suggest a plausible value for a declared prompt variable.
 *
 * Matched on the variable name so the render preview can be filled in one click
 * for the starters above and for common naming conventions. Returns `null` when
 * nothing sensible is known — a wrong suggestion is worse than no suggestion.
 */
export function suggestVariableValue(variable: string): string | null {
  const key = variable.trim().toLowerCase();
  const suggestions: Record<string, string> = {
    question: "What equipment does onboarding provide on day one?",
    context: "New hires receive a laptop, a display, and a headset on day one.",
    text: "The Q3 checkout outage lasted 42 minutes and affected 12% of sessions.",
    notes: "Checkout returned 500s for 42 minutes after a bad config rollout.",
    audience: "executive",
    word_limit: "200",
    sentence_count: "3",
    topic: "onboarding policy",
    language: "English",
    tone: "neutral",
    name: "Ada",
    role: "engineer",
  };
  return suggestions[key] ?? null;
}

// --- Members & teams ---------------------------------------------------------

export const MEMBER_EMAIL_EXAMPLES: readonly Example[] = [
  { label: "Teammate", value: "teammate@company.com" },
  { label: "Analyst", value: "analyst@company.com" },
  { label: "Reviewer", value: "reviewer@company.com" },
];

export const TEAM_NAME_EXAMPLES: readonly Example[] = [
  { label: "Platform", value: "Platform" },
  { label: "Support", value: "Customer Support" },
  { label: "Research", value: "Research" },
];

// --- Approval checkpoint -----------------------------------------------------

export const APPROVAL_REJECT_EXAMPLES: readonly Example[] = [
  {
    label: "Unsupported claims",
    value: "Several claims have no supporting source. Please ground or remove them.",
  },
  {
    label: "Off scope",
    value: "This answers a broader question than the task asked. Narrow the scope.",
  },
  { label: "Too long", value: "Too long for the audience — cut it to a short brief." },
];

export const APPROVAL_EDIT_EXAMPLES: readonly Example[] = [
  {
    label: "Tighten opening",
    value:
      "The Q3 checkout outage lasted 42 minutes and affected 12% of sessions. Root cause: a config rollout that disabled connection pooling.",
  },
  {
    label: "Add next steps",
    value:
      "Next steps: add a pre-deploy config diff gate, and alert on pool saturation above 80%.",
  },
];

// --- Sample corpus -----------------------------------------------------------

/** A built-in document that can be ingested with one click for a demo. */
export interface SampleDocument {
  readonly filename: string;
  /** Short description shown in the UI. */
  readonly summary: string;
  readonly content: string;
}

/**
 * A tiny corpus that makes the retrieval features demonstrable immediately.
 *
 * Plain text/markdown so it needs no extra parser, and deliberately small so
 * ingestion is fast. The content is what `QUERY_EXAMPLES`, `AGENT_EXAMPLES` and
 * `MULTI_AGENT_EXAMPLES` ask about.
 */
export const SAMPLE_DOCUMENTS: readonly SampleDocument[] = [
  {
    filename: "onboarding-policy.md",
    summary: "Equipment, first-week schedule, and probation review.",
    content: [
      "# Engineering Onboarding Policy",
      "",
      "## Equipment provided on day one",
      "",
      "Every new engineer receives a laptop, one external display, a headset, and a",
      "hardware security key on their first day. Requests for a second display are",
      "approved by the hiring manager and fulfilled within five working days.",
      "",
      "## First week",
      "",
      "Day 1: accounts, equipment collection, and a security briefing.",
      "Day 2: architecture walkthrough with the platform team.",
      "Day 3: pair on a starter ticket with an assigned buddy.",
      "Day 4: deploy a change to staging end to end.",
      "Day 5: retrospective with the hiring manager.",
      "",
      "Every new engineer is assigned a buddy for their first thirty days. The buddy",
      "is responsible for daily check-ins during week one.",
      "",
      "## Probation",
      "",
      "The probation period is ninety days. The hiring manager conducts a formal",
      "review at day thirty and again at day ninety. Confirmation requires a written",
      "recommendation from the hiring manager and a second reviewer from the team.",
      "",
      "## Access",
      "",
      "Production access is granted only after the day-thirty review and requires",
      "completion of the on-call training module.",
    ].join("\n"),
  },
  {
    filename: "q3-incident-report.md",
    summary: "Postmortem of the Q3 checkout outage, with follow-up actions.",
    content: [
      "# Q3 Incident Report: Checkout Outage",
      "",
      "## Summary",
      "",
      "On 14 August the checkout service returned HTTP 500 errors for 42 minutes.",
      "Approximately 12% of active sessions were affected. No data was lost.",
      "",
      "## Root cause",
      "",
      "A configuration rollout disabled database connection pooling on the checkout",
      "service. Without pooling, the service opened a new connection per request and",
      "exhausted the database connection limit within four minutes of the rollout.",
      "",
      "## Detection",
      "",
      "An error-rate alert fired three minutes after the rollout began. The on-call",
      "engineer acknowledged it within two minutes.",
      "",
      "## Two rollback approaches considered",
      "",
      "Approach A: revert the configuration change only. Faster, roughly two minutes,",
      "but leaves the newly deployed application build in place.",
      "",
      "Approach B: roll back the full release, both configuration and build. Slower,",
      "roughly eleven minutes, but returns the service to a known-good state.",
      "",
      "The on-call engineer chose Approach A and the error rate returned to baseline",
      "within ninety seconds of the revert.",
      "",
      "## Follow-up actions",
      "",
      "1. Add a pre-deploy configuration diff gate that fails the pipeline when a",
      "   pooling setting changes without an approving reviewer.",
      "2. Alert when connection-pool saturation exceeds 80%.",
      "3. Add a synthetic checkout probe running every thirty seconds.",
    ].join("\n"),
  },
  {
    filename: "product-launch-plan.md",
    summary: "Four-phase launch plan with owners, risks, and mitigations.",
    content: [
      "# Product Launch Plan",
      "",
      "## Phase 1 — Private beta (weeks 1-3)",
      "",
      "Owner: product lead. Twenty design partners, weekly feedback calls, and a",
      "single success metric: task completion without support contact.",
      "",
      "## Phase 2 — Public beta (weeks 4-7)",
      "",
      "Owner: growth lead. Open sign-up with a waitlist, published documentation,",
      "and in-product onboarding.",
      "",
      "## Phase 3 — General availability (week 8)",
      "",
      "Owner: product lead. Pricing published, support rota staffed, and a rollback",
      "plan rehearsed before the announcement.",
      "",
      "## Phase 4 — Post-launch review (week 10)",
      "",
      "Owner: engineering lead. Review adoption, cost per active user, and the",
      "support ticket categories from the first fortnight.",
      "",
      "## Risks and mitigations",
      "",
      "Risk: onboarding drop-off in public beta.",
      "Mitigation: instrument every step and review funnel data weekly.",
      "",
      "Risk: support load exceeds the rota at general availability.",
      "Mitigation: staff a second on-call reviewer for the first two weeks.",
      "",
      "Risk: infrastructure cost grows faster than adoption.",
      "Mitigation: a per-tenant cost dashboard reviewed at each phase gate.",
    ].join("\n"),
  },
];
