import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { MotionFade } from "./MotionFade";
import { Stagger } from "./Stagger";
import { StreamingCursor } from "./StreamingCursor";

/**
 * Task 10.1 — motion primitives collapse to instant under a reduced-motion /
 * test configuration (the global instant-motion flag is set in test setup), so
 * content is always present immediately and no animation is raced.
 * _Requirements: 4.1_
 */
describe("motion primitives (instant under reduced-motion/test)", () => {
  it("MotionFade renders its children immediately", () => {
    render(
      <MotionFade data-testid="fade">
        <p>streamed content</p>
      </MotionFade>,
    );
    expect(screen.getByTestId("fade")).toBeInTheDocument();
    expect(screen.getByText("streamed content")).toBeVisible();
  });

  it("Stagger renders all children immediately in order", () => {
    render(
      <Stagger data-testid="stagger">
        <span>one</span>
        <span>two</span>
        <span>three</span>
      </Stagger>,
    );
    const container = screen.getByTestId("stagger");
    expect(container).toHaveTextContent("onetwothree");
    expect(screen.getByText("two")).toBeInTheDocument();
  });

  it("StreamingCursor renders a static, aria-hidden cursor (no blink)", () => {
    render(<StreamingCursor />);
    const cursor = screen.getByTestId("streaming-cursor");
    expect(cursor).toBeInTheDocument();
    expect(cursor).toHaveAttribute("aria-hidden", "true");
    // Under the instant path it is a plain <span>, not an animating element.
    expect(cursor.tagName).toBe("SPAN");
  });
});
