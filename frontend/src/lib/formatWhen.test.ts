import { describe, it, expect } from "vitest";

import { formatWhen } from "./formatWhen";

/**
 * History lists previously showed raw ISO-8601 (`2026-07-29T07:18:17.352299+00:00`):
 * precise, unreadable, and wider than the column holding it. `now` is injected so the
 * mapping is a pure function rather than a clock-dependent one.
 */
const NOW = new Date("2026-07-31T12:00:00.000Z");

function ago(ms: number): string {
  return new Date(NOW.getTime() - ms).toISOString();
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("formatWhen", () => {
  it.each([
    ["under a minute", 30 * SECOND, "just now"],
    ["one minute", MINUTE, "1 minute ago"],
    ["several minutes", 5 * MINUTE, "5 minutes ago"],
    ["one hour", HOUR, "1 hour ago"],
    ["several hours", 3 * HOUR, "3 hours ago"],
    ["one day", DAY, "1 day ago"],
    ["several days", 3 * DAY, "3 days ago"],
  ])("renders %s", (_label, elapsed, expected) => {
    expect(formatWhen(ago(elapsed), NOW)).toBe(expected);
  });

  it("falls back to an absolute date beyond a week", () => {
    // "412 days ago" answers nothing; a calendar date does.
    const result = formatWhen(ago(30 * DAY), NOW);

    expect(result).not.toContain("ago");
    expect(result).toContain("2026");
  });

  it("treats a future timestamp as just now rather than a negative age", () => {
    // Server/browser clock skew can put a created_at slightly ahead.
    expect(formatWhen(new Date(NOW.getTime() + 5 * SECOND).toISOString(), NOW)).toBe(
      "just now",
    );
  });

  it("returns an unparseable value unchanged instead of inventing a date", () => {
    expect(formatWhen("not-a-date", NOW)).toBe("not-a-date");
  });

  it("handles the exact boundary at one week", () => {
    // Guards the comparison direction at the switch to absolute formatting.
    expect(formatWhen(ago(7 * DAY), NOW)).not.toContain("ago");
    expect(formatWhen(ago(7 * DAY - MINUTE), NOW)).toContain("ago");
  });
});
