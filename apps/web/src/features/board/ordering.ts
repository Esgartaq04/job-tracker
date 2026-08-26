/**
 * Translating a drop into the neighbour pair the API orders by.
 *
 * The board's positions are fractional indices, but that maths lives server-side
 * (`src/services/ranking.py`). The client's whole job is to name the two cards a dropped
 * card should land between; the API turns that pair into a position and decides whether
 * the column needs re-spacing.
 *
 * Kept apart from `Board.tsx` because it is pure: a board, the card being dragged, and
 * the id dnd-kit reports as the drop target are all it needs, which makes the placement
 * rules checkable without a DOM or a simulated drag.
 */

import type { AppStatus, Board, BoardColumn } from "../../api/types";

/** dnd-kit ids for a whole column, namespaced so they can't collide with card ids. */
export const COLUMN_DROP_PREFIX = "column:";

export function columnDropId(status: AppStatus): string {
  return `${COLUMN_DROP_PREFIX}${status}`;
}

/** The status a column droppable refers to, or null when the id is a card's. */
export function statusFromColumnDropId(id: string): AppStatus | null {
  return id.startsWith(COLUMN_DROP_PREFIX)
    ? (id.slice(COLUMN_DROP_PREFIX.length) as AppStatus)
    : null;
}

export function columnOf(board: Board | undefined, cardId: string): AppStatus | undefined {
  return board?.columns.find((column) => column.items.some((item) => item.id === cardId))?.status;
}

/**
 * Where a dropped card should land. `beforeId` is the neighbour above it and `afterId`
 * the one below; either being null means "no neighbour on that side", which the API
 * reads as the top or the bottom of the column.
 */
export interface DropPlacement {
  toStatus: AppStatus;
  beforeId: string | null;
  afterId: string | null;
}

/**
 * Returns null when the drop is a no-op or lands somewhere unrecognised — dropping a card
 * on itself, or on an id that belongs to no column — so the caller can skip the mutation.
 */
export function resolveDrop(
  board: Board | undefined,
  activeId: string,
  overId: string,
): DropPlacement | null {
  if (!board || activeId === overId) return null;

  // Dropping on a column (its header or its empty space) vs. on another card.
  const droppedOnColumn = statusFromColumnDropId(overId);
  const toStatus = droppedOnColumn ?? columnOf(board, overId);
  if (!toStatus) return null;

  const target: BoardColumn | undefined = board.columns.find(
    (column) => column.status === toStatus,
  );
  // The dragged card is not its own neighbour: within-column moves would otherwise
  // measure against the position it is leaving.
  const items = (target?.items ?? []).filter((item) => item.id !== activeId);

  if (droppedOnColumn !== null) {
    // Open space — append to the bottom of the column.
    return { toStatus, beforeId: items.at(-1)?.id ?? null, afterId: null };
  }

  const index = items.findIndex((item) => item.id === overId);
  if (index < 0) return { toStatus, beforeId: null, afterId: null };

  // Land above the card being hovered: its predecessor is "before", it is "after".
  return {
    toStatus,
    beforeId: index > 0 ? items[index - 1].id : null,
    afterId: items[index].id,
  };
}
