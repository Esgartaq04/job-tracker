import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ApplicationDetail } from "../../api/types";
import { makeApplication } from "../../test/fixtures";
import { DescriptionEditor } from "./DescriptionEditor";

const RAW = "Skip to content\nApply now\nAbout the role\nBuild the ledger.\n© Example";
const CLEAN = "## About the role\nBuild the ledger.";

function renderEditor(overrides: Partial<ApplicationDetail>) {
  const application = { ...makeApplication({ id: "a1", ...overrides }), events: [] };
  render(
    <QueryClientProvider client={new QueryClient()}>
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

  it("puts the user's own edit above both", () => {
    renderEditor({ description_raw: RAW, description_clean: CLEAN, description_user: "Mine" });

    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show original" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore original" })).toBeInTheDocument();
  });
});
