import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AiKeyState, ApplicationDetail } from "../../api/types";
import { useUi } from "../../lib/store";
import { makeApplication } from "../../test/fixtures";
import { DescriptionEditor } from "./DescriptionEditor";

const RAW = "Skip to content\nApply now\nAbout the role\nBuild the ledger.\n© Example";
const CLEAN = "## About the role\nBuild the ledger.";

const USABLE_KEY: AiKeyState = { has_key: true, hint: "…TEST", status: "ok", updated_at: null };
const NO_KEY: AiKeyState = { has_key: false, hint: null, status: null, updated_at: null };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;

/** Answers `/ai-key` itself; `other` handles whatever else a test sends. */
function serve(aiKey: AiKeyState = USABLE_KEY, other?: (url: string) => Response | undefined) {
  fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/ai-key")) return json(aiKey);
    const response = other?.(url);
    if (!response) throw new Error(`unexpected request: ${url}`);
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
}

beforeEach(() => {
  localStorage.setItem("job-tracker.token", "t");
  useUi.setState({ aiKeyDialogOpen: false, toast: null });
  serve();
});
afterEach(() => vi.unstubAllGlobals());

function renderEditor(overrides: Partial<ApplicationDetail>) {
  const application = { ...makeApplication({ id: "a1", ...overrides }), events: [] };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DescriptionEditor application={application} />
    </QueryClientProvider>,
  );
}

describe("DescriptionEditor", () => {
  it("shows the cleaned description by default and the original on request", () => {
    renderEditor({ description_raw: RAW, description_clean: CLEAN });

    expect(screen.getByText(/Build the ledger/).textContent).toBe(CLEAN);
    expect(screen.getByText(/nothing reworded/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show original" }));
    expect(screen.getByText(/Build the ledger/).textContent).toBe(RAW);

    fireEvent.click(screen.getByRole("button", { name: "Show cleaned" }));
    expect(screen.getByText(/Build the ledger/).textContent).toBe(CLEAN);
  });

  it("offers a clean-up when there isn't one, and says why an attempt was discarded", () => {
    renderEditor({
      description_raw: RAW,
      extraction_meta: { cleanup: { status: "rejected", reason: "it reworded the description" } },
    });

    expect(screen.getByRole("button", { name: "Clean up" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show original" })).not.toBeInTheDocument();
    expect(screen.getByText(/AI clean-up discarded \(it reworded the description\)/)).toBeInTheDocument();
  });

  it("turns Clean up into Add Claude key without a key", async () => {
    serve(NO_KEY);
    renderEditor({ description_raw: RAW });

    fireEvent.click(await screen.findByRole("button", { name: "Add Claude key to clean up" }));

    expect(useUi.getState().aiKeyDialogOpen).toBe(true);
    expect(screen.queryByRole("button", { name: "Clean up" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("clean-description"))).toBe(false);
  });

  it("turns Clean up into Add Claude key when Claude rejected the saved key", async () => {
    serve({ ...USABLE_KEY, status: "rejected" });
    renderEditor({ description_raw: RAW });

    expect(await screen.findByRole("button", { name: "Add Claude key to clean up" })).toBeInTheDocument();
  });

  it("shows the error and opens the key dialog when the server rejects the key", async () => {
    const rejected = "Claude rejected your saved key. Replace it under 👤 → Claude API key.";
    serve(USABLE_KEY, (url) =>
      url.endsWith("/clean-description") ? json({ detail: rejected }, 424) : undefined,
    );
    renderEditor({ description_raw: RAW });

    fireEvent.click(await screen.findByRole("button", { name: "Clean up" }));

    await waitFor(() => expect(useUi.getState().aiKeyDialogOpen).toBe(true));
    expect(useUi.getState().toast).toEqual({ message: rejected, tone: "error" });
  });

  it("only shows the error, without the key dialog, when clean-up fails for another reason", async () => {
    serve(USABLE_KEY, (url) =>
      url.endsWith("/clean-description") ? json({ detail: "Claude is rate-limited." }, 429) : undefined,
    );
    renderEditor({ description_raw: RAW });

    fireEvent.click(await screen.findByRole("button", { name: "Clean up" }));

    await waitFor(() =>
      expect(useUi.getState().toast).toEqual({ message: "Claude is rate-limited.", tone: "error" }),
    );
    expect(useUi.getState().aiKeyDialogOpen).toBe(false);
  });

  it("puts the user's own edit above both", () => {
    renderEditor({ description_raw: RAW, description_clean: CLEAN, description_user: "Mine" });

    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show original" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore original" })).toBeInTheDocument();
  });
});
