import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AiKeyState, ApplicationDetail, CoverLetter as Letter } from "../../api/types";
import { useUi } from "../../lib/store";
import { makeApplication } from "../../test/fixtures";
import { CoverLetter } from "./CoverLetter";

const LETTER: Letter = {
  id: "d1",
  application_id: "a1",
  content: "Dear Acme hiring team,\n\nI built a ledger.\n\nSincerely,\nEsteven",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: null,
};

const USABLE_KEY: AiKeyState = { has_key: true, hint: "…TEST", status: "ok", updated_at: null };
const NO_KEY: AiKeyState = { has_key: false, hint: null, status: null, updated_at: null };
const REJECTED_KEY: AiKeyState = { ...USABLE_KEY, status: "rejected" };

type Route = (url: string, init?: RequestInit) => Response | undefined;
let fetchMock: ReturnType<typeof vi.fn>;

/** `/ai-key` is answered here so a test only says what is special about its key. */
function serve(route: Route, aiKey: AiKeyState = USABLE_KEY) {
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/ai-key")) return json(aiKey);
    const response = route(url, init);
    if (!response) throw new Error(`unexpected request: ${url}`);
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderTab(overrides: Partial<ApplicationDetail>) {
  const application = { ...makeApplication({ id: "a1", ...overrides }), events: [] };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CoverLetter application={application} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem("job-tracker.token", "t");
  useUi.setState({ aiKeyDialogOpen: false, toast: null });
});
afterEach(() => vi.unstubAllGlobals());

describe("CoverLetter", () => {
  it("waits for the clean-up before offering to write a letter", async () => {
    serve(() => json({ detail: "No cover letter yet" }, 404));
    renderTab({ description_raw: "Apply now. About the role…" });

    expect(screen.getByText(/Waiting for the description to be cleaned up/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clean up now" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
  });

  it("asks for a key instead of a resume when there is none", async () => {
    serve(() => json({ detail: "No cover letter yet" }, 404), NO_KEY);
    renderTab({ description_raw: "raw", description_clean: "About the role…" });

    const add = await screen.findByRole("button", { name: "Add Claude key" });
    expect(screen.getByText("Add your Claude API key to use cover letters.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/resume/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();

    fireEvent.click(add);
    expect(useUi.getState().aiKeyDialogOpen).toBe(true);
  });

  it("asks for a new key instead of a resume when Claude rejected the saved one", async () => {
    serve(() => json({ detail: "No cover letter yet" }, 404), REJECTED_KEY);
    renderTab({ description_raw: "raw", description_clean: "About the role…" });

    expect(await screen.findByRole("button", { name: "Add Claude key" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/resume/i)).not.toBeInTheDocument();
  });

  it("lets you back out of regenerating when there is no key", async () => {
    serve((url) => (url.endsWith("/cover-letter") ? json(LETTER) : undefined), NO_KEY);
    renderTab({ description_raw: "raw", description_clean: "About the role" });

    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    expect(await screen.findByRole("button", { name: "Add Claude key" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByDisplayValue(/I built a ledger/)).toBeInTheDocument();
  });

  it("turns Clean up now into Add Claude key to clean up when there is no key", async () => {
    serve(() => json({ detail: "No cover letter yet" }, 404), NO_KEY);
    renderTab({ description_raw: "Apply now. About the role…" });

    const add = await screen.findByRole("button", { name: "Add Claude key to clean up" });
    expect(screen.queryByRole("button", { name: "Clean up now" })).not.toBeInTheDocument();

    fireEvent.click(add);
    expect(useUi.getState().aiKeyDialogOpen).toBe(true);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("shows the error and opens the key dialog when the server says the key is missing", async () => {
    const missing = "Add your Claude API key (👤 → Claude API key) to use this.";
    serve((url, init) => {
      if (url.endsWith("/cover-letter") && init?.method === "POST") return json({ detail: missing }, 428);
      if (url.endsWith("/cover-letter")) return json({ detail: "No cover letter yet" }, 404);
      return undefined;
    });
    renderTab({ description_raw: "raw", description_clean: "About the role" });

    const generate = await screen.findByRole("button", { name: "Generate cover letter" });
    const resume = new File(["%PDF-1.7"], "resume.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Your resume/), { target: { files: [resume] } });
    fireEvent.click(generate);

    await waitFor(() => expect(useUi.getState().aiKeyDialogOpen).toBe(true));
    expect(useUi.getState().toast).toEqual({ message: missing, tone: "error" });
  });

  it("only shows the error, without the key dialog, when generation fails for another reason", async () => {
    serve((url, init) => {
      if (url.endsWith("/cover-letter") && init?.method === "POST") {
        return json({ detail: "Your Claude account is out of credit." }, 402);
      }
      if (url.endsWith("/cover-letter")) return json({ detail: "No cover letter yet" }, 404);
      return undefined;
    });
    renderTab({ description_raw: "raw", description_clean: "About the role" });

    const generate = await screen.findByRole("button", { name: "Generate cover letter" });
    const resume = new File(["%PDF-1.7"], "resume.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Your resume/), { target: { files: [resume] } });
    fireEvent.click(generate);

    expect(await screen.findByRole("alert")).toHaveTextContent("out of credit");
    expect(useUi.getState().aiKeyDialogOpen).toBe(false);
  });

  it("uploads the resume with the request and shows the letter it gets back", async () => {
    serve((url, init) => {
      if (url.endsWith("/cover-letter") && init?.method === "POST") return json(LETTER);
      if (url.endsWith("/cover-letter")) return json({ detail: "No cover letter yet" }, 404);
      return undefined;
    });
    renderTab({ description_raw: "raw", description_clean: "About the role" });

    const generate = await screen.findByRole("button", { name: "Generate cover letter" });
    expect(generate).toBeDisabled();

    const resume = new File(["%PDF-1.7"], "resume.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Your resume/), { target: { files: [resume] } });
    fireEvent.change(screen.getByLabelText(/Anything to mention/), {
      target: { value: "Referred by Ana" },
    });
    fireEvent.click(generate);

    expect(await screen.findByDisplayValue(/I built a ledger/)).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    const form = init.body as FormData;
    expect((form.get("resume") as File).name).toBe("resume.pdf");
    expect(form.get("notes")).toBe("Referred by Ana");
    // Multipart: the browser must set the boundary, so no JSON Content-Type.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("downloads the saved letter as .docx, and only once edits are saved", async () => {
    serve((url) => {
      if (url.endsWith("/cover-letter.docx")) {
        return new Response(new Blob(["docx"]), {
          headers: { "Content-Disposition": "attachment; filename*=UTF-8''Cover%20Letter.docx" },
        });
      }
      if (url.endsWith("/cover-letter")) return json(LETTER);
      return undefined;
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderTab({ description_raw: "raw", description_clean: "About the role" });
    const download = await screen.findByRole("button", { name: "Download .docx" });

    fireEvent.change(screen.getByLabelText("Cover letter"), { target: { value: "edited" } });
    expect(download).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Cover letter"), { target: { value: LETTER.content } });
    expect(download).toBeEnabled();

    fireEvent.click(download);
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/a1/cover-letter.docx"))).toBe(true);
  });
});
