import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OrgContextBadge } from "./OrgContextBadge";
import { ErrorBanner } from "./ErrorBanner";
import { EmptyState } from "./EmptyState";
import { RetryNotice } from "./RetryNotice";
import { mapError } from "../api/errors";
import { makeSession, renderWithSession } from "../test/renderWithSession";

/**
 * Task 7.4 — component tests for the shared components.
 * _Requirements: 4.1, 5.1, 5.2, 5.5, 5.6_
 */
describe("shared components", () => {
  it("OrgContextBadge shows the Org_Context + Role (4.1)", () => {
    renderWithSession(<OrgContextBadge />, makeSession("admin"));
    expect(screen.getByTestId("org-context-org")).toHaveTextContent("org-1");
    expect(screen.getByTestId("org-context-role")).toHaveTextContent("admin");
  });

  it("OrgContextBadge renders nothing when unauthenticated", () => {
    renderWithSession(<OrgContextBadge />, makeSession(null));
    expect(screen.queryByTestId("org-context-badge")).toBeNull();
  });

  it("ErrorBanner renders the message + field errors for 422 (5.1, 5.2)", () => {
    const error = mapError(422, {
      error: {
        code: "validation_error",
        message: "Request validation failed.",
        details: { errors: [{ loc: ["body", "email"], msg: "field required" }] },
      },
    });
    render(<ErrorBanner error={error} />);
    expect(screen.getByTestId("error-message")).toHaveTextContent(
      "Request validation failed.",
    );
    expect(screen.getByTestId("error-field-errors")).toHaveTextContent("email");
    expect(screen.getByTestId("error-field-errors")).toHaveTextContent(
      "field required",
    );
  });

  it("ErrorBanner renders a generic 500 message with no stack (5.5)", () => {
    const error = mapError(500, {
      error: {
        code: "internal_error",
        message: "An internal error occurred while processing the request.",
        details: {},
      },
    });
    render(<ErrorBanner error={error} />);
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "server");
    expect(banner.textContent ?? "").not.toContain("traceback");
    expect(banner.textContent ?? "").not.toContain("    at ");
  });

  it("EmptyState renders a title, message, and action", () => {
    render(
      <EmptyState
        title="No documents yet"
        message="Upload a file to get started."
        action={<button>Upload</button>}
      />,
    );
    expect(screen.getByTestId("empty-state")).toHaveTextContent("No documents yet");
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("RetryNotice offers a retry action (5.6)", async () => {
    const onRetry = vi.fn();
    render(<RetryNotice onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
