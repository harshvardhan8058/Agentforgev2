/**
 * `StreamingAnswer`: a progressive, token-by-token reveal of a completed answer.
 *
 * `POST /query` returns the full answer in one response (there is no server
 * token stream for retrieval), so this reveals that answer incrementally on the
 * client for a live, "typing" feel — mirroring the agent-run experience. Once
 * fully revealed it renders the authoritative `Markdown` (so inline `[n]`
 * markers become citation links, Property 15). Under reduced motion or in tests
 * (`useInstantMotion`) it renders the full markdown immediately, so nothing is
 * ever hidden and tests never race an animation.
 */
import type { JSX } from "react";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "../../components/markdown/Markdown";
import { StreamingCursor } from "../../components/motion/StreamingCursor";
import { useInstantMotion } from "../../components/motion/motion-config";
import type { Citation } from "../../api/domain";

export function StreamingAnswer({
  text,
  citations,
}: {
  text: string;
  citations: Citation[];
}): JSX.Element {
  const instant = useInstantMotion();
  const [count, setCount] = useState(instant ? text.length : 0);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (instant) {
      setCount(text.length);
      return;
    }
    // Reveal the full answer over roughly two seconds regardless of length,
    // so long answers don't feel slow and short ones still animate.
    setCount(0);
    let current = 0;
    const step = Math.max(1, Math.ceil(text.length / 120));
    let last = 0;
    const tick = (ts: number): void => {
      if (ts - last >= 16) {
        current = Math.min(text.length, current + step);
        setCount(current);
        last = ts;
      }
      if (current < text.length) {
        frameRef.current = requestAnimationFrame(tick);
      }
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== undefined) cancelAnimationFrame(frameRef.current);
    };
  }, [text, instant]);

  const done = count >= text.length;

  if (done) {
    return <Markdown content={text} citations={citations} />;
  }

  return (
    <div
      className="whitespace-pre-wrap text-sm leading-relaxed text-text"
      data-testid="streaming-answer"
      aria-hidden="true"
    >
      {text.slice(0, count)}
      <StreamingCursor />
    </div>
  );
}
