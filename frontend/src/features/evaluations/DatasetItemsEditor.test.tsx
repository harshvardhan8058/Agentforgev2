// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  DatasetItemsEditor,
  emptyItem,
  toRequestItems,
  type DraftItem,
} from "./DatasetItemsEditor";
import { EVALUATION_ITEM_PRESETS } from "../../lib/examples";

/**
 * The dataset item editor.
 *
 * The create-dataset form used to send `items: []` unconditionally, so every
 * dataset was empty. The framework scores each item in a dataset, so an empty
 * one yields no results and an aggregate of exactly 0 — the feature could not do
 * anything, and there was no control for adding an item.
 *
 * `toRequestItems` is the boundary that matters: `input` is `min_length=1`
 * server-side, so a blank row would fail validation for the entire request, and
 * `expected` is an optional field that must be `null` rather than `""`.
 */
describe("toRequestItems", () => {
  it("drops rows with a blank input", () => {
    // A blank row would otherwise fail min_length=1 and reject the whole request.
    const items: DraftItem[] = [
      { input: "a", expected: "x" },
      { input: "   ", expected: "ignored" },
      { input: "", expected: "" },
    ];

    expect(toRequestItems(items)).toEqual([{ input: "a", expected: "x" }]);
  });

  it("sends a blank expected as null, not an empty string", () => {
    // The contract types `expected` as `string | null`; "" is a different claim.
    expect(toRequestItems([{ input: "a", expected: "  " }])).toEqual([
      { input: "a", expected: null },
    ]);
  });

  it("trims both fields", () => {
    expect(toRequestItems([{ input: "  a  ", expected: "  x  " }])).toEqual([
      { input: "a", expected: "x" },
    ]);
  });

  it("returns an empty list when nothing is filled in", () => {
    expect(toRequestItems([emptyItem()])).toEqual([]);
  });
});

describe("DatasetItemsEditor", () => {
  function renderEditor(initial: DraftItem[] = [emptyItem()]): {
    onChange: ReturnType<typeof vi.fn>;
  } {
    const onChange = vi.fn();
    render(<DatasetItemsEditor items={initial} onChange={onChange} />);
    return { onChange };
  }

  it("warns while no item would be saved", () => {
    renderEditor();

    expect(screen.getByTestId("dataset-items-empty-warning")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-item-count").textContent).toContain("0 will");
  });

  it("stops warning once an item has an input", () => {
    renderEditor([{ input: "a question", expected: "an answer" }]);

    expect(
      screen.queryByTestId("dataset-items-empty-warning"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("dataset-item-count").textContent).toContain("1 will");
  });

  it("warns when an item has no expected answer", () => {
    // exact_match and contains both score 0 without one, so such an item can
    // only ever fail — worth saying out loud rather than scoring a silent zero.
    renderEditor([{ input: "a question", expected: "" }]);

    expect(screen.getByTestId("dataset-items-expected-warning")).toBeInTheDocument();
  });

  it("adds a row", async () => {
    const { onChange } = renderEditor();

    await userEvent.click(screen.getByTestId("dataset-item-add"));

    expect(onChange).toHaveBeenCalledWith([emptyItem(), emptyItem()]);
  });

  it("removes a row", async () => {
    const { onChange } = renderEditor([
      { input: "first", expected: "" },
      { input: "second", expected: "" },
    ]);

    await userEvent.click(screen.getByTestId("dataset-item-remove-0"));

    expect(onChange).toHaveBeenCalledWith([{ input: "second", expected: "" }]);
  });

  it("never lets the last row be removed", () => {
    // An editor with zero rows would offer no way to add the first item back.
    renderEditor();

    expect(screen.getByTestId("dataset-item-remove-0")).toBeDisabled();
  });

  it("edits an input in place", async () => {
    const { onChange } = renderEditor();

    await userEvent.type(screen.getByTestId("dataset-item-input-0"), "q");

    expect(onChange).toHaveBeenCalledWith([{ input: "q", expected: "" }]);
  });

  it("loads a preset set of items", async () => {
    const { onChange } = renderEditor();
    const preset = EVALUATION_ITEM_PRESETS[0];

    await userEvent.click(screen.getByRole("button", { name: preset.label }));

    expect(onChange).toHaveBeenCalledWith(preset.items.map((i) => ({ ...i })));
  });

  it("labels every field", () => {
    // Two fields per row, so unlabelled inputs would be indistinguishable.
    renderEditor();

    expect(screen.getByLabelText("Input")).toBeInTheDocument();
    expect(screen.getByLabelText("Expected")).toBeInTheDocument();
  });
});

describe("EVALUATION_ITEM_PRESETS", () => {
  it("gives every item an expected answer", () => {
    // A preset without expectations would produce a run that scores zero and
    // look exactly like the bug this editor fixes.
    for (const preset of EVALUATION_ITEM_PRESETS) {
      expect(preset.items.length).toBeGreaterThan(0);
      for (const item of preset.items) {
        expect(item.input.trim().length).toBeGreaterThan(0);
        expect(item.expected.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("survives the request boundary intact", () => {
    for (const preset of EVALUATION_ITEM_PRESETS) {
      const sent = toRequestItems(preset.items.map((i) => ({ ...i })));
      expect(sent).toHaveLength(preset.items.length);
      expect(sent.every((i) => i.expected !== null)).toBe(true);
    }
  });
});
