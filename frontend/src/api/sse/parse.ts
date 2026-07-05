/**
 * Pure SSE frame parser (Property 10).
 *
 * Parses one backend frame of the form:
 *
 *     event: <type>\n
 *     data: <json>\n
 *     \n
 *
 * into `{ type, data }`, where `data` is the parsed JSON object (which always
 * embeds a monotonic `sequence`). Returns `null` for any frame that is not a
 * well-formed `event`/`data` pair with a JSON-object payload. Pure and never
 * throws.
 */

/** One parsed SSE frame: an event `type` and its decoded JSON `data` object. */
export interface SseFrame {
  type: string;
  data: Record<string, unknown>;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Parse a single raw SSE frame into an `SseFrame`, or `null` if unparseable.
 *
 * Tolerates a trailing blank line and CRLF line endings; requires exactly one
 * `event:` field and one `data:` field whose value decodes to a JSON object.
 */
export function parseSseFrame(raw: unknown): SseFrame | null {
  if (typeof raw !== "string") return null;

  // Normalize CRLF, drop the trailing frame-delimiter blank line(s).
  const lines = raw.replace(/\r\n/g, "\n").split("\n");

  let type: string | null = null;
  const dataLines: string[] = [];
  let sawData = false;

  for (const line of lines) {
    if (line === "") continue; // blank separator line(s)
    if (line.startsWith("event:")) {
      if (type !== null) return null; // more than one event field
      type = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      sawData = true;
      // Per the SSE spec a single leading space after the colon is stripped.
      let value = line.slice("data:".length);
      if (value.startsWith(" ")) value = value.slice(1);
      dataLines.push(value);
    } else {
      // Any non-empty line that is neither event nor data makes the frame
      // unparseable in our (constrained) backend vocabulary.
      return null;
    }
  }

  if (type === null || type.length === 0 || !sawData) return null;

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }
  if (!isPlainObject(data)) return null;

  return { type, data };
}

/** Serialize a frame in the backend wire format (used by tests and transport). */
export function renderSseFrame(type: string, data: Record<string, unknown>): string {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}
