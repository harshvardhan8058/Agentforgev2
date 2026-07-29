// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  GeneralKnowledgeNotice,
  NO_GROUNDING_MESSAGE,
  isGeneralKnowledgeAnswer,
} from "./GeneralKnowledgeNotice";

/**
 * An ungrounded answer must be labelled as model knowledge — but a *refusal* is not a
 * general-knowledge answer, so the two ungrounded cases have to stay distinguishable.
 */
describe("isGeneralKnowledgeAnswer", () => {
  it("is true for an ungrounded answer with real content", () => {
    expect(isGeneralKnowledgeAnswer(false, "France won the 1998 World Cup.")).toBe(true);
  });

  it("is false for the backend's refusal message", () => {
    expect(isGeneralKnowledgeAnswer(false, NO_GROUNDING_MESSAGE)).toBe(false);
    // Tolerates incidental surrounding whitespace.
    expect(isGeneralKnowledgeAnswer(false, `  ${NO_GROUNDING_MESSAGE}  `)).toBe(false);
  });

  it("is false whenever the answer is grounded", () => {
    expect(isGeneralKnowledgeAnswer(true, "The stipend is 25000.")).toBe(false);
  });
});

describe("GeneralKnowledgeNotice", () => {
  it("states plainly that the answer did not come from the corpus", () => {
    render(<GeneralKnowledgeNotice />);
    const notice = screen.getByTestId("general-knowledge-notice");
    expect(notice.textContent).toContain("Not from your documents");
    expect(notice.textContent).toContain("no citations");
  });
});
