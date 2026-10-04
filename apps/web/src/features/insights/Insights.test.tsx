import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity, Flow, Funnel, Velocity } from "../../api/types";
import { usePrefs } from "../../lib/prefs";
import { buildWeeks, levelFor } from "./ActivityHeatmap";
import { Insights } from "./Insights";

const FUNNEL: Funnel = {
  total: 5,
  applied: 4,
  stages: [],
  response_rate: 0.5,
  median_days_to_first_response: 6,
};

const FLOW: Flow = {
  total_applied: 4,
  nodes: [
    { id: "applied", label: "Applied", value: 4 },
    { id: "interview", label: "Interview", value: 1 },
    { id: "offer", label: "Offer", value: 1 },
    { id: "rejected", label: "Rejected", value: 1 },
    { id: "no_reply", label: "No reply yet", value: 2 },
  ],
  links: [
    { source: "applied", target: "interview", value: 1 },
    { source: "interview", target: "offer", value: 1 },
    { source: "applied", target: "rejected", value: 1 },
    { source: "applied", target: "no_reply", value: 2 },
  ],
};

const VELOCITY: Velocity = { weekly: [{ week_start: "2026-09-28", saved: 1, applied: 4 }], stale_count: 0 };

const ACTIVITY: Activity = {
  days: [
    { date: "2026-10-03", count: 1 },
    { date: "2026-10-04", count: 3 },
  ],
  current_streak: 2,
  longest_streak: 5,
  this_week: 3,
};

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  usePrefs.setState({ weeklyGoal: 10 });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/stats/funnel")) return json(FUNNEL);
      if (url.includes("/stats/flow")) return json(FLOW);
      if (url.includes("/stats/velocity")) return json(VELOCITY);
      if (url.includes("/stats/activity")) return json(ACTIVITY);
      throw new Error(`unexpected request: ${url}`);
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function renderInsights() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Insights />
    </QueryClientProvider>,
  );
}

describe("Insights", () => {
  it("leads with the total applied and the streak", async () => {
    renderInsights();
    const total = await screen.findByText("Total applied");
    expect(total.nextElementSibling).toHaveTextContent("4");
    expect(screen.getByText("2 days")).toBeInTheDocument();
    expect(screen.getByText("best 5")).toBeInTheDocument();
  });

  it("draws a Sankey node for every stage the API returns", async () => {
    renderInsights();
    await screen.findByText("Total applied");
    const chart = screen.getByRole("img", { name: /flow of 4 applications/i });
    for (const label of ["Applied", "Interview", "Offer", "Rejected", "No reply yet"]) {
      expect(chart).toHaveTextContent(label);
    }
  });

  it("fills the XP bar towards the weekly goal", async () => {
    renderInsights();
    const bar = await screen.findByRole("progressbar", { name: /applications this week/i });
    expect(bar).toHaveAttribute("aria-valuetext", "3 of 10");
    expect(screen.getByText(/3 \/ 10 this week · 7 to go/)).toBeInTheDocument();
  });
});

describe("buildWeeks", () => {
  it("pads the first week back to Monday and the last forward to Sunday", () => {
    // 2026-10-01 is a Thursday.
    const weeks = buildWeeks([
      { date: "2026-10-01", count: 0 },
      { date: "2026-10-02", count: 1 },
      { date: "2026-10-03", count: 2 },
      { date: "2026-10-04", count: 5 },
      { date: "2026-10-05", count: 3 },
    ]);
    expect(weeks).toHaveLength(2);
    expect(weeks[0].slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0][3]?.date).toBe("2026-10-01");
    expect(weeks[1][0]?.date).toBe("2026-10-05");
    expect(weeks[1].slice(1)).toEqual([null, null, null, null, null, null]);
  });

  it("covers 182 days in 26 or 27 full weeks", () => {
    const start = Date.UTC(2026, 3, 6);
    const days = Array.from({ length: 182 }, (_, offset) => ({
      date: new Date(start + offset * 86_400_000).toISOString().slice(0, 10),
      count: 0,
    }));
    const weeks = buildWeeks(days);
    expect(weeks.every((week) => week.length === 7)).toBe(true);
    expect(weeks.flat().filter(Boolean)).toHaveLength(182);
    expect(weeks.length).toBeGreaterThanOrEqual(26);
    expect(weeks.length).toBeLessThanOrEqual(27);
  });

  it("uses fixed thresholds for block shades", () => {
    expect([0, 1, 2, 3, 4, 5, 12].map(levelFor)).toEqual([0, 1, 2, 3, 3, 4, 4]);
  });
});
