/**
 * `useSseRun`: drives an SSE run over a pure reducer (Req 9.1–9.3, 9.7).
 *
 * Owns an `AbortController` and feeds every parsed frame from the `streamSse`
 * transport into the supplied pure reducer, exposing the accumulated reducer
 * `state`, whether a stream is currently open (`isStreaming`), any normalized
 * transport/open error, and `start` / `cancel` controls. `cancel` aborts the
 * underlying fetch and closes the client subscription (Req 9.7).
 *
 * The reducer is pure and property-tested (Properties 8 and 9); this hook only
 * wires the transport to it and manages React state, so the streaming logic
 * stays testable without a live stream.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { streamSse } from "../../api/sse/stream";
import type { SseFrame } from "../../api/sse/parse";
import type { ClientError } from "../../api/errors";

/** Configuration for a run: the pure reducer and its initial state. */
export interface UseSseRunConfig<S> {
  reducer: (state: S, frame: SseFrame) => S;
  initialState: S;
}

/** The run API exposed to a view. */
export interface SseRun<S> {
  /** Reducer-accumulated stream state. */
  state: S;
  /** True while a stream is open. */
  isStreaming: boolean;
  /** A normalized open/transport error, if the stream failed. */
  error: ClientError | null;
  /** Open a stream: POST `body` to `path` and fold frames into the reducer. */
  start(path: string, body: unknown): void;
  /** Abort the fetch + close the client subscription (Req 9.7). */
  cancel(): void;
}

export function useSseRun<S>({ reducer, initialState }: UseSseRunConfig<S>): SseRun<S> {
  const [state, setState] = useState<S>(initialState);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<ClientError | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const stateRef = useRef<S>(initialState);

  // Keep a ref of the latest state so the frame callback folds correctly even
  // across rapid, batched updates.
  stateRef.current = state;

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setIsStreaming(false);
  }, []);

  const start = useCallback(
    (path: string, body: unknown) => {
      // Abort any in-flight stream before starting a new one.
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      stateRef.current = initialState;
      setState(initialState);
      setError(null);
      setIsStreaming(true);

      void streamSse({
        path,
        body,
        signal: controller.signal,
        onFrame: (frame) => {
          const next = reducer(stateRef.current, frame);
          stateRef.current = next;
          setState(next);
        },
      })
        .catch((err: ClientError) => {
          setError(err);
        })
        .finally(() => {
          // Only clear the streaming flag if this controller is still current
          // (a newer run may have superseded it).
          if (controllerRef.current === controller) {
            controllerRef.current = null;
            setIsStreaming(false);
          }
        });
    },
    [reducer, initialState],
  );

  // Abort on unmount so a background stream never updates a dead component.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  return { state, isStreaming, error, start, cancel };
}
