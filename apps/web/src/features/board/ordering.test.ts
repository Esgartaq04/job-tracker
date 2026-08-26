import { describe, expect, it } from "vitest";

import { makeBoard as board } from "../../test/fixtures";
import { columnDropId, resolveDrop, statusFromColumnDropId } from "./ordering";

describe("resolveDrop", () => {
  describe("where the card lands", () => {
    it("puts a card dropped on the first one above it, at the top of the column", () => {
      const placement = resolveDrop(board({ saved: ["dragged"], applied: ["a", "b", "c"] }), "dragged", "a");

      // No neighbour above means the top: the API reads a null `beforeId` that way.
      expect(placement).toEqual({ toStatus: "applied", beforeId: null, afterId: "a" });
    });

    it("puts a card dropped on the column at the bottom, below the last card", () => {
      const placement = resolveDrop(
        board({ saved: ["dragged"], applied: ["a", "b", "c"] }),
        "dragged",
        columnDropId("applied"),
      );

      expect(placement).toEqual({ toStatus: "applied", beforeId: "c", afterId: null });
    });

    it("puts a card dropped on a middle card between that card and its predecessor", () => {
      const placement = resolveDrop(board({ saved: ["dragged"], applied: ["a", "b", "c"] }), "dragged", "b");

      expect(placement).toEqual({ toStatus: "applied", beforeId: "a", afterId: "b" });
    });

    it("gives a card dropped on an empty column no neighbours at all", () => {
      const placement = resolveDrop(board({ saved: ["dragged"], applied: [] }), "dragged", columnDropId("applied"));

      expect(placement).toEqual({ toStatus: "applied", beforeId: null, afterId: null });
    });

    it("moves a card into the column of the card it was dropped on", () => {
      const placement = resolveDrop(board({ saved: ["dragged"], interview: ["a", "b"] }), "dragged", "b");

      expect(placement?.toStatus).toBe("interview");
    });
  });

  describe("a card is never its own neighbour", () => {
    // Reordering within a column is where this bites: leaving the dragged card in the
    // list would name the position it is vacating as the neighbour to measure against.
    it("skips the dragged card when it sits directly above the drop target", () => {
      const placement = resolveDrop(board({ applied: ["a", "b", "c"] }), "b", "c");

      expect(placement).toEqual({ toStatus: "applied", beforeId: "a", afterId: "c" });
    });

    it("skips the dragged card when it is the last one and the drop is on the column", () => {
      const placement = resolveDrop(board({ applied: ["a", "b", "c"] }), "c", columnDropId("applied"));

      expect(placement).toEqual({ toStatus: "applied", beforeId: "b", afterId: null });
    });

    it("leaves a single-card column with no neighbours when that card is the one moving", () => {
      const placement = resolveDrop(board({ applied: ["only"] }), "only", columnDropId("applied"));

      expect(placement).toEqual({ toStatus: "applied", beforeId: null, afterId: null });
    });
  });

  describe("drops that should not move anything", () => {
    it("ignores a card dropped on itself", () => {
      expect(resolveDrop(board({ applied: ["a", "b"] }), "a", "a")).toBeNull();
    });

    it("ignores a drop target that belongs to no column", () => {
      expect(resolveDrop(board({ applied: ["a", "b"] }), "a", "not-on-the-board")).toBeNull();
    });

    it("ignores a drop that arrives before the board has loaded", () => {
      expect(resolveDrop(undefined, "a", "b")).toBeNull();
    });
  });
});

describe("column drop ids", () => {
  it("round-trips a status", () => {
    expect(statusFromColumnDropId(columnDropId("phone_screen"))).toBe("phone_screen");
  });

  it("does not mistake a card id for a column id", () => {
    expect(statusFromColumnDropId("8f14e45f-ceea-467a-9c4b-1f2a3b4c5d6e")).toBeNull();
  });
});
