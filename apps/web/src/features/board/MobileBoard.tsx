import { useEffect, useRef, useState } from "react";

import { useBoard, useMoveApplication } from "../../api/hooks";
import type { AppStatus } from "../../api/types";
import { STATUSES, STATUS_LABELS } from "../../api/types";
import { ageLabel, faviconFor } from "../../lib/format";
import { useUi } from "../../lib/store";

/**
 * Below 768px the board is one column with a segmented status switcher (README §7.5).
 * Drag-and-drop is not the interaction here: a long-press drag inside a scrolling list
 * fights the scroll on touch, so each card carries the status control instead — which
 * is also the "menu equivalent" §7.6 asks for.
 */
export function MobileBoard() {
  const query = useUi((state) => state.query);
  const openDrawer = useUi((state) => state.openDrawer);
  const notify = useUi((state) => state.notify);
  const { data: board, isLoading } = useBoard(query || undefined);
  const [status, setStatus] = useState<AppStatus>("saved");
  const move = useMoveApplication();
  const tabs = useRef<HTMLDivElement>(null);

  const counts = new Map(board?.columns.map((column) => [column.status, column.count]) ?? []);
  const column = board?.columns.find((entry) => entry.status === status);

  // Keep the selected tab in view when it changes from off-screen.
  useEffect(() => {
    tabs.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({
      inline: "center",
      block: "nearest",
      behavior: "smooth",
    });
  }, [status]);

  if (isLoading || !board) {
    return <div className="p-4 text-sm text-slate-500">Loading…</div>;
  }

  return (
    <div className="flex h-full flex-col">
      <div
        ref={tabs}
        role="tablist"
        aria-label="Board columns"
        className="flex gap-1 overflow-x-auto border-b border-surface-border px-3 py-2"
      >
        {STATUSES.map((entry) => (
          <button
            key={entry}
            role="tab"
            aria-selected={entry === status}
            onClick={() => setStatus(entry)}
            className={[
              "shrink-0 rounded-full px-3 py-1.5 text-xs transition",
              entry === status
                ? "bg-accent text-white"
                : "bg-surface-card text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {STATUS_LABELS[entry]}
            <span className="ml-1.5 tabular-nums opacity-70">{counts.get(entry) ?? 0}</span>
          </button>
        ))}
      </div>

      <ul className="flex-1 space-y-2 overflow-y-auto p-3">
        {(column?.items ?? []).map((application) => (
          <li
            key={application.id}
            className="rounded-lg border border-surface-border bg-surface-card p-3"
          >
            <button
              type="button"
              onClick={() => openDrawer(application.id)}
              className="flex w-full items-start gap-2 text-left"
            >
              {faviconFor(application) ? (
                <img src={faviconFor(application) as string} alt="" className="mt-0.5 h-4 w-4 rounded-sm" />
              ) : (
                <span className="mt-0.5 h-4 w-4 rounded-sm bg-surface-border" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-slate-100">
                  {application.title ?? "Untitled"}
                </span>
                <span className="block truncate text-xs text-slate-400">
                  {application.company ?? "Unknown company"}
                  {application.location ? ` · ${application.location}` : ""}
                </span>
              </span>
              <span
                className={[
                  "shrink-0 text-[11px]",
                  application.staleness === "warn" ? "text-stale-warn" : "text-slate-500",
                ].join(" ")}
              >
                {ageLabel(application)}
              </span>
            </button>

            <label className="mt-2 flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Status</span>
              <select
                value={application.status}
                onChange={(event) => {
                  const toStatus = event.target.value as AppStatus;
                  move.mutate(
                    { id: application.id, toStatus },
                    {
                      onSuccess: () => notify(`Moved to ${STATUS_LABELS[toStatus]}`),
                      onError: () => notify("Couldn't move that card", "error"),
                    },
                  );
                }}
                aria-label={`Status of ${application.title ?? "this application"}`}
                className="flex-1 rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-xs text-slate-300"
              >
                {STATUSES.map((entry) => (
                  <option key={entry} value={entry}>
                    {STATUS_LABELS[entry]}
                  </option>
                ))}
              </select>
            </label>
          </li>
        ))}

        {(column?.items.length ?? 0) === 0 && (
          <li className="py-10 text-center text-sm text-slate-600">
            Nothing in {STATUS_LABELS[status]}
          </li>
        )}
      </ul>
    </div>
  );
}
