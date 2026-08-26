/**
 * Regression cover for "Make the whole column a drop target, and stop the highlight lying".
 *
 * That commit fixed three things in one interaction, two of which are checkable here:
 * the droppable node had been the inner card list, leaving the header as a strip where a
 * drop silently did nothing; and the highlight used dnd-kit's own `isOver`, which is true
 * only when the *column itself* is the drop target — so hovering a card (and cards stack
 * from the top) left the top of a column looking dead.
 *
 * The third fix, swapping `closestCorners` for `pointerWithin`, is not covered: collision
 * detection ranks droppables by element geometry, and jsdom reports every element as 0x0.
 * There is nothing for it to rank here, so a test would assert on a fiction.
 */

import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AppStatus } from "../../api/types";
import { useUi } from "../../lib/store";
import { makeColumn } from "../../test/fixtures";
import { Column } from "./Column";
import { columnDropId } from "./ordering";

/**
 * dnd-kit decides what is under the cursor from real layout, which jsdom does not have.
 * Standing in for `useDroppable` lets a test say "this is the drop target right now" and
 * ask what the column does about it. The library boundary is mocked; the component is not.
 */
const dnd = vi.hoisted(() => ({
  over: null as { id: string } | null,
  nodes: new Map<string, HTMLElement>(),
}));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...actual,
    useDroppable: ({ id }: { id: string | number }) => {
      const key = String(id);
      return {
        setNodeRef: (node: HTMLElement | null) => {
          if (node) dnd.nodes.set(key, node);
        },
        over: dnd.over,
        // Exactly what the real hook reports: true only when this droppable is itself the
        // target. A column that highlights off this alone is the bug being guarded against.
        isOver: dnd.over?.id === key,
        active: null,
        rect: { current: null },
        node: { current: null },
      };
    },
  };
});

function Providers({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <DndContext>{children}</DndContext>
    </QueryClientProvider>
  );
}

function renderColumn(status: AppStatus, ids: string[]) {
  render(<Column column={makeColumn(status, ids)} />, { wrapper: Providers });
  return dnd.nodes.get(columnDropId(status));
}

/**
 * The drop affordance is purely visual — no ARIA state carries it — so the accent styling
 * on the column's root is the only thing a test can observe. Matching on "accent" rather
 * than the exact ring/background utilities keeps a restyle from failing this falsely.
 */
function isHighlighted(element: HTMLElement | undefined): boolean {
  return element !== undefined && /accent/.test(element.className);
}

beforeEach(() => {
  dnd.over = null;
  dnd.nodes.clear();
  useUi.setState({ collapsed: {} });
});

describe("a column as a drop target", () => {
  it("takes the whole column, so the header is droppable too", () => {
    const dropNode = renderColumn("applied", ["a", "b"]);
    const root = screen.getByRole("region", { name: /applied column/i });

    // The header used to sit outside the droppable, which made the top ~33px of every
    // column a strip where a drop landed nowhere.
    expect(dropNode).toBe(root);
    expect(dropNode).toContainElement(screen.getByRole("heading", { name: /applied/i }));
  });

  it("is droppable while collapsed, so a tidied-away column can still be moved into", () => {
    useUi.setState({ collapsed: { applied: true } });

    const dropNode = renderColumn("applied", ["a"]);

    // Collapsed, the column is a single button — its name comes from the count and label.
    expect(dropNode).toBe(screen.getByRole("button", { name: /applied/i }));
  });
});

describe("the drop highlight", () => {
  it("shows when the column itself is the drop target", () => {
    dnd.over = { id: columnDropId("applied") };

    expect(isHighlighted(renderColumn("applied", ["a", "b"]))).toBe(true);
  });

  it("shows when a card inside the column is the drop target", () => {
    // The bug: hovering a card makes that card the target, not the column, so the column
    // went dark exactly where its cards are — the top. The drop worked; the affordance lied.
    dnd.over = { id: "b" };

    expect(isHighlighted(renderColumn("applied", ["a", "b", "c"]))).toBe(true);
  });

  it("shows when the first card is the drop target, at the very top of the column", () => {
    dnd.over = { id: "a" };

    expect(isHighlighted(renderColumn("applied", ["a", "b", "c"]))).toBe(true);
  });

  it("shows on a collapsed column that is the drop target", () => {
    useUi.setState({ collapsed: { applied: true } });
    dnd.over = { id: columnDropId("applied") };

    expect(isHighlighted(renderColumn("applied", ["a"]))).toBe(true);
  });

  it("stays off when the drop target is a card in a different column", () => {
    // The over-correction to guard against: highlighting on any drag at all.
    dnd.over = { id: "card-in-another-column" };

    expect(isHighlighted(renderColumn("applied", ["a", "b"]))).toBe(false);
  });

  it("stays off when the column itself is not the target and holds no cards", () => {
    dnd.over = { id: columnDropId("interview") };

    expect(isHighlighted(renderColumn("applied", []))).toBe(false);
  });

  it("stays off when nothing is being dragged", () => {
    dnd.over = null;

    expect(isHighlighted(renderColumn("applied", ["a", "b"]))).toBe(false);
  });
});
