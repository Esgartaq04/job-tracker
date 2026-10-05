import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUi } from "../../lib/store";
import { Drawer } from "./Drawer";

beforeEach(() => {
  useUi.setState({ drawerId: null });
  // The drawer's own content doesn't matter here; leave it loading.
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
});

afterEach(() => vi.unstubAllGlobals());

function renderWithOpener() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <div data-focus-fallback tabIndex={-1} data-testid="fallback">
        <button type="button">Opener</button>
      </div>
      <Drawer />
    </QueryClientProvider>,
  );
  const fallback = document.querySelector<HTMLElement>("[data-testid=fallback]")!;
  const opener = fallback.querySelector("button")!;
  opener.focus();
  act(() => useUi.getState().openDrawer("a-1"));
  return { fallback, opener };
}

describe("Drawer focus", () => {
  it("hands focus back to whatever opened it", () => {
    const { opener } = renderWithOpener();
    expect(opener).not.toHaveFocus();
    act(() => useUi.getState().closeDrawer());
    expect(opener).toHaveFocus();
  });

  it("falls back to the opener's container when the opener is gone", () => {
    const { fallback, opener } = renderWithOpener();
    opener.remove();
    act(() => useUi.getState().closeDrawer());
    expect(fallback).toHaveFocus();
  });
});
