import { useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  pointerWithin,
  rectIntersection,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";

import { useBoard, useMoveApplication } from "../../api/hooks";
import type { Application, AppStatus, Board as BoardData } from "../../api/types";
import { STATUS_LABELS } from "../../api/types";
import { useUi } from "../../lib/store";
import { Card } from "./Card";
import { Column } from "./Column";

/**
 * Where the cursor is, is where you mean to drop.
 *
 * `closestCorners` ranks by distance between the dragged rect's corners and each
 * droppable's. A column is a tall rect, so hovering near its top is still far from its
 * bottom corners — a small card droppable elsewhere could win, and the intended column
 * lost to it. `pointerWithin` asks the only question that matches intent: which
 * droppables contain the pointer? Nested ones come back innermost-first, so hovering a
 * card targets that card (for ordering) and hovering open space targets the column.
 *
 * The fallbacks matter: `pointerWithin` returns nothing once the cursor leaves every
 * droppable (dragging past the board edge), and the keyboard sensor has no pointer at all.
 */
const collisionDetection: CollisionDetection = (args) => {
  const pointer = pointerWithin(args);
  if (pointer.length > 0) return pointer;

  const intersecting = rectIntersection(args);
  if (intersecting.length > 0) return intersecting;

  return closestCorners(args);
};

function findApplication(board: BoardData | undefined, id: string): Application | undefined {
  return board?.columns.flatMap((column) => column.items).find((item) => item.id === id);
}

function columnOf(board: BoardData | undefined, id: string): AppStatus | undefined {
  return board?.columns.find((column) => column.items.some((item) => item.id === id))?.status;
}

export function Board() {
  const query = useUi((state) => state.query);
  const notify = useUi((state) => state.notify);
  const { data: board, isLoading, error } = useBoard(query || undefined);
  const move = useMoveApplication();
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const sensors = useSensors(
    // 5px activation keeps a click on the card opening the drawer.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const dragging = useMemo(
    () => (draggingId ? findApplication(board, draggingId) : undefined),
    [board, draggingId],
  );

  function handleDragStart(event: DragStartEvent) {
    setDraggingId(String(event.active.id));
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setDraggingId(null);
    if (!over || !board) return;

    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId === overId) return;

    // Dropping on a column header/empty area vs. on another card.
    const toStatus = overId.startsWith("column:")
      ? (overId.slice("column:".length) as AppStatus)
      : columnOf(board, overId);
    if (!toStatus) return;

    const target = board.columns.find((column) => column.status === toStatus);
    const items = (target?.items ?? []).filter((item) => item.id !== activeId);

    let beforeId: string | null = null;
    let afterId: string | null = null;
    if (!overId.startsWith("column:")) {
      const index = items.findIndex((item) => item.id === overId);
      if (index >= 0) {
        // Land above the card we're hovering: its predecessor is "before".
        beforeId = index > 0 ? items[index - 1].id : null;
        afterId = items[index].id;
      }
    } else {
      // Dropped into open space — append to the bottom of the column.
      beforeId = items.at(-1)?.id ?? null;
    }

    move.mutate(
      { id: activeId, toStatus, beforeId, afterId },
      {
        onError: () => notify(`Couldn't move that card to ${STATUS_LABELS[toStatus]}`, "error"),
        onSuccess: () => {
          if (toStatus === "offer") notify("Offer! 🎉");
        },
      },
    );
  }

  if (error) {
    return (
      <p className="p-8 text-sm text-stale-warn">Couldn&apos;t load the board: {String(error)}</p>
    );
  }

  if (isLoading || !board) {
    return (
      <div className="flex gap-3 overflow-x-auto p-4">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="h-64 w-72 shrink-0 animate-pulse rounded-lg bg-surface-raised/50"
          />
        ))}
      </div>
    );
  }

  const empty = board.columns.every((column) => column.count === 0);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDraggingId(null)}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Picked up card ${active.id}`,
          onDragOver: ({ over }) =>
            over ? `Over ${String(over.id).replace("column:", "")}` : "Not over a column",
          onDragEnd: ({ over }) =>
            over ? `Dropped into ${String(over.id).replace("column:", "")}` : "Drop cancelled",
          onDragCancel: () => "Move cancelled",
        },
      }}
    >
      {empty ? (
        <div className="mx-auto mt-24 max-w-md text-center">
          <h2 className="text-lg font-medium text-slate-200">Nothing tracked yet</h2>
          <p className="mt-2 text-sm text-slate-400">
            Paste a job posting URL in the bar above — press <kbd className="rounded bg-surface-card px-1">/</kbd>{" "}
            to focus it. The card appears immediately and fills itself in.
          </p>
        </div>
      ) : (
        <div className="flex h-full gap-3 overflow-x-auto p-4">
          {board.columns.map((column) => (
            <Column key={column.status} column={column} />
          ))}
        </div>
      )}

      <DragOverlay dropAnimation={{ duration: 180, easing: "cubic-bezier(0.18,0.67,0.6,1.22)" }}>
        {dragging ? (
          <div className="w-72">
            <Card application={dragging} overlay />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
