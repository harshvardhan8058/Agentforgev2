/**
 * Last-line-of-defence cleanup for model-generated text.
 *
 * The agent loop instructs the model to answer with a decision envelope —
 * `{"action": "final", "answer": "..."}` — and the API unwraps it before the
 * text ever reaches this client. That unwrapping is where the problem belongs
 * and where it is fixed; a model can nevertheless produce a malformed envelope
 * shape nobody has seen yet, and the failure mode is uniquely bad: the operator
 * is shown raw JSON where an answer should be.
 *
 * So the render boundary re-checks. This is deliberately *narrow*: text that
 * does not both begin with `{` and carry an `"action"` key is returned
 * byte-identical, so ordinary prose — including prose that merely discusses
 * JSON — is never touched.
 */

/** Matches an `"action": "..."` key, the marker of a decision envelope. */
const ENVELOPE_SHAPE = /["']?action["']?\s*:\s*["'][a-z_]+["']/i;

/** Locates the opening quote of an answer-bearing string value. */
const ANSWER_KEY = /["']?(?:answer|content|text|response)["']?\s*:\s*"/;

/** A backslash directly followed by a real newline: a half-escaped line break. */
const DANGLING_ESCAPE = /\\[ \t]*\r?\n/g;

/** Three or more newlines, left behind once escape sequences are resolved. */
const EXCESS_BLANK_LINES = /\n{3,}/g;

/** A Markdown code fence, optionally language-tagged. */
const CODE_FENCE = /^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$/g;

/** True when `text` looks like a raw decision envelope rather than prose. */
export function looksLikeDecisionEnvelope(text: string): boolean {
  const stripped = text.replace(CODE_FENCE, "").trim();
  return stripped.startsWith("{") && ENVELOPE_SHAPE.test(stripped);
}

/** Resolve the escape sequences a model emits inside an answer string. */
function unescapeAnswer(raw: string): string {
  // Half-escaped line breaks first, so the `\\` rule cannot consume them.
  let out = raw.replace(DANGLING_ESCAPE, "\n");
  for (const [token, replacement] of [
    ["\\n", "\n"],
    ["\\r", ""],
    ["\\t", "\t"],
    ['\\"', '"'],
    ["\\/", "/"],
    ["\\\\", "\\"],
  ] as const) {
    out = out.split(token).join(replacement);
  }
  return out.replace(EXCESS_BLANK_LINES, "\n\n").trim();
}

/**
 * Return the prose inside a decision envelope, or `text` unchanged when it is
 * not one.
 *
 * When the envelope carries no recoverable prose the original text is returned
 * rather than an empty string: showing something imperfect beats showing an
 * empty answer card with no explanation.
 */
export function stripDecisionEnvelope(text: string): string {
  if (!looksLikeDecisionEnvelope(text)) return text;

  const stripped = text.replace(CODE_FENCE, "").trim();
  const match = ANSWER_KEY.exec(stripped);
  if (match !== null) {
    let body = stripped.slice(match.index + match[0].length);
    const closing = body.lastIndexOf('"');
    // Anything after that final quote is structure (`"`, `}`, `]`, `,`), not content.
    if (closing !== -1 && /^[\s},\]]*$/.test(body.slice(closing + 1))) {
      body = body.slice(0, closing);
    }
    const recovered = unescapeAnswer(body);
    if (recovered.length > 0) return recovered;
  }

  // No answer key: drop the lines that are pure JSON structure.
  const kept = stripped
    .split("\n")
    .map((line) => unescapeAnswer(line))
    .filter(
      (line) =>
        line.length > 0 &&
        !ENVELOPE_SHAPE.test(line) &&
        line.replace(/[{}[\],"' \t]/g, "").length > 0,
    );
  const recovered = kept.join("\n").replace(EXCESS_BLANK_LINES, "\n\n").trim();
  return recovered.length > 0 ? recovered : text;
}
