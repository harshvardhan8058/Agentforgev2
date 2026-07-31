import { describe, it, expect } from "vitest";

import { RANGE_PRESETS, toDateTimeLocal } from "./rangePresets";

/**
 * The quick-range presets for the usage dashboard.
 *
 * `resolve` takes `now` as an argument specifically so this mapping is a pure
 * function of it rather than of the wall clock, which is what makes these
 * assertions exact instead of approximate.
 */
describe("toDateTimeLocal", () => {
  it("formats as the local YYYY-MM-DDTHH:mm a datetime-local input requires", () => {
    // Local components, not UTC: the input displays local time, so a UTC-based
    // format would silently shift the range by the viewer's offset.
    const date = new Date(2026, 2, 9, 7, 5);

    expect(toDateTimeLocal(date)).toBe("2026-03-09T07:05");
  });

  it("zero-pads single-digit month, day, hour and minute", () => {
    expect(toDateTimeLocal(new Date(2026, 0, 2, 3, 4))).toBe("2026-01-02T03:04");
  });
});

describe("RANGE_PRESETS", () => {
  const now = new Date(2026, 6, 28, 14, 30);

  it("offers a stable, non-empty set of labelled presets", () => {
    expect(RANGE_PRESETS.length).toBeGreaterThan(0);
    const labels = RANGE_PRESETS.map((p) => p.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it.each([
    ["Last 24 hours", "2026-07-27T14:30"],
    ["Last 7 days", "2026-07-21T14:30"],
    ["Last 30 days", "2026-06-28T14:30"],
    ["Month to date", "2026-07-01T00:00"],
  ])("%s starts at %s and ends now", (label, expectedStart) => {
    const preset = RANGE_PRESETS.find((p) => p.label === label);
    expect(preset).toBeDefined();

    const [start, end] = (preset as (typeof RANGE_PRESETS)[number]).resolve(now);

    expect(start).toBe(expectedStart);
    expect(end).toBe("2026-07-28T14:30");
  });

  it("resolves 'All time' to two blank bounds", () => {
    // Blank means the query omits the params entirely, which is the API's
    // "everything" case — not a very wide explicit range.
    const preset = RANGE_PRESETS.find((p) => p.label === "All time");

    expect(preset?.resolve(now)).toEqual(["", ""]);
  });

  it("never resolves a start after its end", () => {
    for (const preset of RANGE_PRESETS) {
      const [start, end] = preset.resolve(now);
      if (start.length > 0 && end.length > 0) {
        expect(start <= end).toBe(true);
      }
    }
  });
});
