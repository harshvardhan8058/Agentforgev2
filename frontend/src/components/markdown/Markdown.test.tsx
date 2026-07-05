import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Markdown } from "./Markdown";
import type { Citation } from "../../api/domain";

const citations: Citation[] = [
  { document_id: "doc-1", chunk_id: "chunk-1" },
  { document_id: "doc-2", chunk_id: "chunk-2" },
];

describe("Markdown renderer with inline citations", () => {
  it("renders GFM markdown content", () => {
    render(<Markdown content={"# Title\n\nSome **bold** text."} />);
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
  });

  it("turns an in-range [n] marker into a citation link to its source", () => {
    render(
      <Markdown content={"Grounded answer [1] with support."} citations={citations} />,
    );
    const link = screen.getByTestId("citation-1");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("data-document-id", "doc-1");
    expect(link).toHaveAttribute("data-chunk-id", "chunk-1");
  });

  it("leaves an out-of-range marker inert (no link)", () => {
    render(<Markdown content={"Bad ref [9] here."} citations={citations} />);
    expect(screen.queryByTestId("citation-9")).toBeNull();
    expect(screen.getByTestId("markdown")).toHaveTextContent("[9]");
  });
});
