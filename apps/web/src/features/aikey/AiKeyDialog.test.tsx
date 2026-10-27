import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUi } from "../../lib/store";
import { AiKeyDialog } from "./AiKeyDialog";

const KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789WXYZ";
const EMPTY = { has_key: false, hint: null, status: null, updated_at: null };

type Route = (url: string, init?: RequestInit) => Response | undefined;
let fetchMock: ReturnType<typeof vi.fn>;
let queryClient: QueryClient;

function serve(route: Route) {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const response = route(url, init);
    if (!response) throw new Error(`unexpected request: ${url}`);
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderDialog() {
  useUi.getState().openAiKeyDialog();
  render(
    <QueryClientProvider client={queryClient}>
      <AiKeyDialog />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem("job-tracker.token", "t");
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => {
  // Runs while the dialog may still be mounted, so the store update needs an act().
  act(() => useUi.getState().closeAiKeyDialog());
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("AiKeyDialog", () => {
  it("saves, clears the input, and shows only the hint", async () => {
    let state: Record<string, unknown> = EMPTY;
    serve((_, init) => {
      if (init?.method === "PUT") {
        expect(JSON.parse(String(init.body))).toEqual({ api_key: KEY });
        state = { has_key: true, hint: "…WXYZ", status: "ok", updated_at: "2026-10-26T00:00:00Z" };
      }
      return json(state);
    });
    renderDialog();
    fireEvent.change(await screen.findByLabelText("Claude API key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByText(/…WXYZ/)).toBeInTheDocument();
    expect((screen.getByLabelText("Claude API key") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("abcdefghij");
    expect(JSON.stringify({ ...localStorage })).not.toContain("sk-ant");

    // The key rides along in the one PUT and lives nowhere the client keeps state.
    const cached = JSON.stringify(queryClient.getQueryCache().getAll().map((q) => q.state.data));
    const variables = JSON.stringify(
      queryClient.getMutationCache().getAll().map((m) => m.state.variables),
    );
    expect(cached).not.toContain("sk-ant");
    expect(variables).not.toContain("sk-ant");
    expect(JSON.stringify(useUi.getState())).not.toContain("sk-ant");
  });

  it("shows the server's reason when Claude refuses the key", async () => {
    serve((_, init) =>
      init?.method === "PUT" ? json({ detail: "Claude didn't accept this key." }, 422) : json(EMPTY),
    );
    renderDialog();
    fireEvent.change(await screen.findByLabelText("Claude API key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByText("Claude didn't accept this key.")).toBeInTheDocument();
  });

  it("asks before removing, then sends DELETE", async () => {
    serve((_, init) =>
      init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : json({ has_key: true, hint: "…WXYZ", status: "ok", updated_at: null }),
    );
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/ai-key"),
      expect.objectContaining({ method: "DELETE" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove it" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/ai-key"),
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    // Back to the no-key state once the server confirms.
    await waitFor(() => expect(screen.queryByText("…WXYZ")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Remove key" })).not.toBeInTheDocument();
  });

  it("backs out of a removal without sending anything", async () => {
    serve(() => json({ has_key: true, hint: "…WXYZ", status: "ok", updated_at: null }));
    renderDialog();
    fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Remove key" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(
      true,
    );
  });

  it("tells the user a rejected key needs replacing", async () => {
    serve(() => json({ has_key: true, hint: "…WXYZ", status: "rejected", updated_at: null }));
    renderDialog();
    expect(await screen.findByText(/rejected/i)).toBeInTheDocument();
  });

  it("closes on Escape and when the backdrop is clicked", async () => {
    serve(() => json(EMPTY));
    renderDialog();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    act(() => useUi.getState().openAiKeyDialog());
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("forgets a half-typed key when the dialog closes", async () => {
    serve(() => json(EMPTY));
    renderDialog();
    fireEvent.change(await screen.findByLabelText("Claude API key"), { target: { value: KEY } });

    act(() => useUi.getState().closeAiKeyDialog());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => useUi.getState().openAiKeyDialog());
    expect(((await screen.findByLabelText("Claude API key")) as HTMLInputElement).value).toBe("");
  });

  it("explains itself and links to the Anthropic console", async () => {
    serve(() => json(EMPTY));
    renderDialog();
    expect(await screen.findByText(/Stored encrypted; never shown again/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /console\.anthropic\.com/ });
    expect(link).toHaveAttribute("href", "https://console.anthropic.com/settings/keys");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
    expect(screen.getByText(/separate key for this app with a monthly spend limit/)).toBeInTheDocument();
    expect(screen.getByLabelText("Claude API key")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Claude API key")).toHaveAttribute("autocomplete", "off");
  });
});
