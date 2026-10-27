import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import type { AiKeyState } from "../../api/types";
import { aiUsable, isAiKeyError } from "./aiKeyErrors";

const state = (overrides: Partial<AiKeyState>): AiKeyState => ({
  has_key: true,
  hint: "…TEST",
  status: "ok",
  updated_at: null,
  ...overrides,
});

describe("isAiKeyError", () => {
  it("is true for a missing (428) or rejected (424) key", () => {
    expect(isAiKeyError(new ApiError(428, "missing"))).toBe(true);
    expect(isAiKeyError(new ApiError(424, "rejected"))).toBe(true);
  });

  it("is false for every other failure", () => {
    for (const status of [400, 401, 402, 429, 502, 503]) {
      expect(isAiKeyError(new ApiError(status, "nope"))).toBe(false);
    }
    expect(isAiKeyError(new Error("network down"))).toBe(false);
    expect(isAiKeyError(undefined)).toBe(false);
  });
});

describe("aiUsable", () => {
  it("lets the attempt go ahead while the key state is unknown", () => {
    expect(aiUsable(undefined)).toBe(true);
  });

  it("is true for a saved key Claude has accepted or not yet judged", () => {
    expect(aiUsable(state({ status: "ok" }))).toBe(true);
    expect(aiUsable(state({ status: null }))).toBe(true);
  });

  it("is false with no key, or with one Claude rejected", () => {
    expect(aiUsable(state({ has_key: false, hint: null, status: null }))).toBe(false);
    expect(aiUsable(state({ status: "rejected" }))).toBe(false);
  });
});
