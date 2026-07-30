// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CopyableId, shortenId } from "./CopyableId";

const UUID = "a188d54b-524b-4f8a-9589-64e6a9406d1b";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/**
 * `shortenId` elides the middle rather than truncating, so two ids can still be
 * told apart by eye — a plain prefix truncation would render sibling ids from the
 * same generator identically.
 */
describe("shortenId", () => {
  it("elides the middle of a long identifier", () => {
    expect(shortenId(UUID)).toBe("a188d54b…6d1b");
  });

  it("keeps both ends so two ids remain distinguishable", () => {
    const a = shortenId("aaaaaaaa-1111-1111-1111-000000000001");
    const b = shortenId("aaaaaaaa-1111-1111-1111-000000000002");

    expect(a).not.toBe(b);
  });

  it("returns a short value unchanged", () => {
    // Shortening would make it longer, not shorter.
    expect(shortenId("abc")).toBe("abc");
  });

  it("returns a value exactly at the threshold unchanged", () => {
    const exact = "1234567890123";
    expect(shortenId(exact)).toBe(exact);
  });

  it("handles an empty string", () => {
    expect(shortenId("")).toBe("");
  });
});

describe("CopyableId", () => {
  it("shows the shortened id and the full value as a title", () => {
    render(<CopyableId value={UUID} testId="org" />);

    expect(screen.getByTestId("org-value").textContent).toBe("a188d54b…6d1b");
    expect(screen.getByTestId("org-value")).toHaveAttribute("title", UUID);
  });

  it("copies the full value, not the shortened one", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<CopyableId value={UUID} label="organization id" testId="org" />);

    await userEvent.click(screen.getByTestId("org-copy"));

    expect(writeText).toHaveBeenCalledWith(UUID);
  });

  it("names the copy control after what it copies", () => {
    render(<CopyableId value={UUID} label="organization id" testId="org" />);

    expect(
      screen.getByRole("button", { name: "Copy organization id" }),
    ).toBeInTheDocument();
  });

  it("confirms the copy", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    render(<CopyableId value={UUID} label="organization id" testId="org" />);

    await userEvent.click(screen.getByTestId("org-copy"));

    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("copied"),
    );
  });

  it("falls back to execCommand outside a secure context", async () => {
    // navigator.clipboard is absent when the console is served over plain HTTP
    // on a non-localhost host — a realistic self-hosted deployment.
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const execCommand = vi.fn().mockReturnValue(true);
    (document as any).execCommand = execCommand;
    render(<CopyableId value={UUID} testId="org" />);

    await userEvent.click(screen.getByTestId("org-copy"));

    await waitFor(() => expect(execCommand).toHaveBeenCalledWith("copy"));
    expect(screen.queryByTestId("org-failed")).not.toBeInTheDocument();
  });

  it("reports failure rather than appearing to succeed", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    (document as any).execCommand = vi.fn().mockReturnValue(false);
    render(<CopyableId value={UUID} testId="org" />);

    await userEvent.click(screen.getByTestId("org-copy"));

    await waitFor(() =>
      expect(screen.getByTestId("org-failed")).toBeInTheDocument(),
    );
  });

  it("recovers when the clipboard promise rejects", async () => {
    // A denied permission rejects rather than being absent; the legacy path
    // should still be tried.
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    (document as any).execCommand = execCommand;
    render(<CopyableId value={UUID} testId="org" />);

    await userEvent.click(screen.getByTestId("org-copy"));

    await waitFor(() => expect(execCommand).toHaveBeenCalled());
  });
});
