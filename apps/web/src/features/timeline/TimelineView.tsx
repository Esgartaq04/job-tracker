import { useMemo } from "react";

import { useBoard } from "../../api/hooks";
import { STATUS_LABELS } from "../../api/types";
import { useUi } from "../../lib/store";

const DAY = 86_400_000;

/**
 * Gantt-ish lanes showing how long each application has been alive and when it was
 * applied to. Makes ghosting patterns obvious (README §7.4).
 */
export function TimelineView() {
  const openDrawer = useUi((state) => state.openDrawer);
  const { data: board } = useBoard();

  const { rows, span, start } = useMemo(() => {
    const items = (board?.columns ?? []).flatMap((column) => column.items);
    if (items.length === 0) return { rows: [], span: 1, start: Date.now() };

    const earliest = Math.min(...items.map((item) => new Date(item.saved_at).getTime()));
    const now = Date.now();
    return {
      rows: items.sort((a, b) => a.saved_at.localeCompare(b.saved_at)),
      span: Math.max(now - earliest, DAY * 7),
      start: earliest,
    };
  }, [board]);

  if (rows.length === 0) {
    return <p className="p-8 text-center text-sm text-slate-500">Nothing to plot yet.</p>;
  }

  return (
    <div className="h-full overflow-auto p-4">
      <ul className="space-y-1.5">
        {rows.map((row) => {
          const savedAt = new Date(row.saved_at).getTime();
          const appliedAt = row.applied_at ? new Date(row.applied_at).getTime() : null;
          const closedAt = row.closed_at ? new Date(row.closed_at).getTime() : Date.now();
          const left = ((savedAt - start) / span) * 100;
          const width = Math.max(((closedAt - savedAt) / span) * 100, 1.5);

          return (
            <li
              key={row.id}
              onClick={() => openDrawer(row.id)}
              className="grid cursor-pointer grid-cols-[minmax(0,14rem)_1fr] items-center gap-3 rounded px-1 py-1 hover:bg-surface-card/50"
            >
              <span className="truncate text-xs text-slate-300">
                {row.company ?? "—"} · <span className="text-slate-500">{row.title}</span>
              </span>
              <div className="relative h-4">
                <div
                  className={[
                    "absolute top-1 h-2 rounded-full",
                    row.status === "rejected" || row.status === "ghosted"
                      ? "bg-slate-600"
                      : row.status === "offer"
                        ? "bg-emerald-500"
                        : "bg-accent/70",
                  ].join(" ")}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`${STATUS_LABELS[row.status]} — saved ${row.saved_at.slice(0, 10)}`}
                />
                {appliedAt && (
                  <span
                    className="absolute top-0.5 h-3 w-[3px] rounded bg-slate-100"
                    style={{ left: `${((appliedAt - start) / span) * 100}%` }}
                    title={`Applied ${row.applied_at?.slice(0, 10)}`}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-4 text-center text-xs text-slate-500">
        Bar = time tracked · white tick = applied · grey = closed
      </p>
    </div>
  );
}
