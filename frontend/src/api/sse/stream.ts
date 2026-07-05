/**
 * `streamSse`: the fetch + `ReadableStream` SSE transport (Req 9.1, 10.2).
 *
 * The backend stream endpoints are **POST** returning `text/event-stream`, and
 * the browser `EventSource` API only issues GET — so streaming is done here via
 * `fetch` + `response.body` (a `ReadableStream`). The transport:
 *  - POSTs the JSON body with `Accept: text/event-stream`, attaching the shared
 *    bearer token (mirroring the API_Client auth middleware);
 *  - decodes the byte stream, splits frames on the blank-line delimiter, and
 *    feeds each complete frame to the pure `parseSseFrame`;
 *  - supports cancellation via an `AbortController` `signal` (Req 9.7).
 *
 * It normalizes a non-2xx opening response and any transport failure into a
 * `ClientError` via `mapError`, so callers surface stream failures uniformly.
 */
import { config } from "../../config";
import { getToken } from "../../auth/tokenStore";
import { mapError, type ClientError } from "../errors";
import { parseSseFrame, type SseFrame } from "./parse";

/** Options for opening an SSE stream. */
export interface StreamSseOptions {
  /** The backend path (joined to the configured base URL). */
  path: string;
  /** The JSON request body to POST. */
  body: unknown;
  /** Invoked for every successfully-parsed frame, in received order. */
  onFrame: (frame: SseFrame) => void;
  /** Abort signal for client-side cancellation (Req 9.7). */
  signal?: AbortSignal;
}

/** The frame delimiter in the SSE wire format. */
const FRAME_DELIMITER = /\r?\n\r?\n/;

/**
 * Open the stream and pump frames until the server closes it or the caller
 * aborts. Resolves when the stream ends; throws a `ClientError` on a non-2xx
 * opening response or a transport failure (an `AbortError` resolves quietly).
 */
export async function streamSse(options: StreamSseOptions): Promise<void> {
  const { path, body, onFrame, signal } = options;
  const token = getToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (typeof token === "string" && token.length > 0) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err)) return;
    throw mapError(null, undefined);
  }

  if (!response.ok) {
    // Try to parse an AppError envelope from the failed opening response.
    let errorBody: unknown;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = undefined;
    }
    throw mapError(response.status, errorBody);
  }

  if (response.body === null) {
    // No stream body — nothing to read; treat as a clean, empty stream.
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Emit every complete frame; keep the trailing partial in the buffer.
      let match = FRAME_DELIMITER.exec(buffer);
      while (match !== null) {
        const rawFrame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        emitFrame(rawFrame, onFrame);
        match = FRAME_DELIMITER.exec(buffer);
      }
    }
  } catch (err) {
    if (isAbort(err)) return;
    throw mapError(null, undefined);
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* already released */
    }
  }

  // Flush any trailing frame that was not terminated by a blank line.
  const remainder = buffer.trim();
  if (remainder.length > 0) {
    emitFrame(remainder, onFrame);
  }
}

/** Parse and dispatch one raw frame, ignoring unparseable frames. */
function emitFrame(raw: string, onFrame: (frame: SseFrame) => void): void {
  if (raw.trim().length === 0) return;
  const frame = parseSseFrame(raw);
  if (frame !== null) onFrame(frame);
}

/** True iff `err` is an `AbortError` raised by an aborted fetch/read. */
function isAbort(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name?: unknown }).name === "AbortError"
  );
}

export type { ClientError };
