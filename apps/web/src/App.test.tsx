import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { useUi } from "./lib/store";

// Only the shell is under test: everything that fetches or streams is a stub.
vi.mock("./api/events", () => ({ useServerEvents: () => undefined }));
vi.mock("./features/aikey/AiKeyDialog", () => ({ AiKeyDialog: () => null }));
vi.mock("./features/auth/AccountMenu", () => ({ AccountMenu: () => null }));
vi.mock("./features/auth/SignIn", () => ({ SignIn: () => <p>Sign in</p> }));
vi.mock("./features/board/Board", () => ({ Board: () => null }));
vi.mock("./features/board/MobileBoard", () => ({ MobileBoard: () => null }));
vi.mock("./features/detail/Drawer", () => ({ Drawer: () => null }));
vi.mock("./features/insights/Insights", () => ({ Insights: () => null }));
vi.mock("./features/quickadd/QuickAdd", () => ({ QuickAdd: () => null }));
vi.mock("./features/quickadd/QuickAddSheet", () => ({ QuickAddSheet: () => null }));
vi.mock("./features/reminders/NeedsAttention", () => ({ NeedsAttention: () => null }));
vi.mock("./features/table/TableView", () => ({ TableView: () => null }));
vi.mock("./features/theme/DimensionSwitcher", () => ({ DimensionSwitcher: () => null }));
vi.mock("./lib/useMediaQuery", () => ({ MOBILE_QUERY: "", useMediaQuery: () => false }));

beforeEach(() => {
  localStorage.setItem("job-tracker.token", "t");
  useUi.setState({ aiKeyDialogOpen: false });
});
afterEach(() => localStorage.clear());

describe("App", () => {
  it("closes the key dialog when the session ends, so it doesn't reopen after the next sign-in", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App />
      </QueryClientProvider>,
    );
    act(() => useUi.getState().openAiKeyDialog());

    act(() => {
      window.dispatchEvent(new CustomEvent("job-tracker:signed-out"));
    });

    expect(screen.getByText("Sign in")).toBeInTheDocument();
    expect(useUi.getState().aiKeyDialogOpen).toBe(false);
  });
});
