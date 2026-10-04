import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

import type { BoardColumn } from "../../api/types";
import { STATUS_LABELS } from "../../api/types";
import { useUi } from "../../lib/store";
import { Card } from "./Card";
import { columnDropId } from "./ordering";

export function Column({ column }: { column: BoardColumn }) {
  const collapsed = useUi((state) => state.collapsed[column.status] ?? false);
  const toggleColumn = useUi((state) => state.toggleColumn);
  // Deliberately not useDroppable's own `isOver`: that is true only when the *column
  // itself* is the drop target. Hovering a card makes that card the target, so the column
  // stopped highlighting — and since cards stack from the top, the upper part of a column
  // looked dead while the empty space below it worked. The drop landed correctly either
  // way; the affordance was lying about it.
  const dropId = columnDropId(column.status);
  const { setNodeRef, over } = useDroppable({
    id: dropId,
    data: { status: column.status },
  });

  const overId = over ? String(over.id) : null;
  const isOver =
    overId !== null && (overId === dropId || column.items.some((item) => item.id === overId));

  if (collapsed) {
    return (
      <button
        type="button"
        ref={setNodeRef}
        onClick={() => toggleColumn(column.status)}
        className={[
          "mc-panel flex w-12 shrink-0 flex-col items-center gap-3 py-4 text-slate-400 transition hover:text-slate-200",
          // Collapsed used to mean undroppable, so a card had no way into a column you'd
          // tidied away. It appends to the bottom, same as dropping on empty space.
          isOver ? "border-accent-ink bg-accent/10 text-slate-200" : "",
        ].join(" ")}
        aria-expanded={false}
        title={`Expand ${STATUS_LABELS[column.status]}`}
      >
        <span className="text-xs tabular-nums">{column.count}</span>
        <span className="[writing-mode:vertical-rl] text-xs uppercase tracking-wide">
          {STATUS_LABELS[column.status]}
        </span>
      </button>
    );
  }

  return (
    <section
      ref={setNodeRef}
      className={[
        "mc-panel flex w-72 shrink-0 flex-col transition-colors",
        // The whole column is the target, header included — it used to be just the card
        // list, leaving the header as a strip where a drop silently did nothing.
        isOver ? "bg-accent/10 ring-2 ring-inset ring-accent-ink/60" : "",
      ].join(" ")}
      aria-label={`${STATUS_LABELS[column.status]} column, ${column.count} applications`}
    >
      <header className="flex items-center justify-between px-3 py-2">
        <h2 className="mc-shadow text-xs font-semibold uppercase tracking-wide text-slate-200">
          {STATUS_LABELS[column.status]}{" "}
          <span className="ml-1 text-slate-500 tabular-nums">{column.count}</span>
        </h2>
        <button
          type="button"
          onClick={() => toggleColumn(column.status)}
          className="rounded px-1 text-slate-500 transition hover:text-slate-200"
          aria-expanded
          title="Collapse column"
        >
          ⟨
        </button>
      </header>

      <div className="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-3">
        <SortableContext
          items={column.items.map((item) => item.id)}
          strategy={verticalListSortingStrategy}
        >
          {column.items.map((application) => (
            <Card key={application.id} application={application} />
          ))}
        </SortableContext>

        {column.items.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-600">
            Drop a card here
          </p>
        )}
      </div>
    </section>
  );
}
