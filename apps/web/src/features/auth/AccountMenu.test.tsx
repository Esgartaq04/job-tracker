import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUi } from "../../lib/store";
import { AccountMenu } from "./AccountMenu";

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function renderMenu(state: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(async () => json(state)));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AccountMenu onSignOut={() => {}} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Account" }));
}

beforeEach(() => localStorage.setItem("job-tracker.token", "t"));
afterEach(() => {
  useUi.getState().closeAiKeyDialog();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("AccountMenu: Claude API key", () => {
  it("invites the user to turn AI on when there is no key", async () => {
    renderMenu({ has_key: false, hint: null, status: null, updated_at: null });
    expect(await screen.findByText("Turn on AI features")).toBeInTheDocument();
  });

  it("shows the hint when the key works", async () => {
    renderMenu({ has_key: true, hint: "…WXYZ", status: "ok", updated_at: null });
    expect(await screen.findByText("Connected · …WXYZ")).toBeInTheDocument();
  });

  it("says so when Claude rejected the saved key", async () => {
    renderMenu({ has_key: true, hint: "…WXYZ", status: "rejected", updated_at: null });
    expect(await screen.findByText("Rejected — replace it")).toBeInTheDocument();
  });

  it("opens the dialog and closes the menu", async () => {
    renderMenu({ has_key: false, hint: null, status: null, updated_at: null });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Claude API key/ }));
    expect(useUi.getState().aiKeyDialogOpen).toBe(true);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
