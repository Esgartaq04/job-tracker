import { useMemo } from "react";

import { useBoard } from "../../api/hooks";
import { STATUS_LABELS } from "../../api/types";
import { ageLabel, formatDate } from "../../lib/format";
import { useUi } from "../../lib/store";

/** Dense sortable grid with CSV export — better than a board for "everything from March". */
export function TableView() {
  const query = useUi((state) => state.query);
  const openDrawer = useUi((state) => state.openDrawer);
  const { data: board } = useBoard(query || undefined);

  const rows = useMemo(
    () =>
      (board?.columns ?? [])
        .flatMap((column) => column.items)
        .sort((a, b) => b.saved_at.localeCompare(a.saved_at)),
    [board],
  );

  function exportCsv() {
    const header = ["company", "title", "status", "location", "saved_at", "applied_at", "url"];
    const csv = [
      header.join(","),
      ...rows.map((row) =>
        [
          row.company,
          row.title,
          row.status,
          row.location,
          row.saved_at,
          row.applied_at,
          row.source_url,
        ]
          .map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`)
          .join(","),
      ),
    ].join("\n");

    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `applications-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex h-full flex-col overflow-hidden p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-400">{rows.length} applications</p>
        <button
          type="button"
          onClick={exportCsv}
          className="rounded-md border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:border-accent hover:text-slate-100"
        >
          Export CSV
        </button>
      </div>

      <div className="flex-1 overflow-auto rounded-lg border border-surface-border">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-surface-raised text-xs uppercase tracking-wide text-slate-400">
            <tr>
              {["Company", "Role", "Status", "Location", "Age", "Applied"].map((label) => (
                <th key={label} className="px-3 py-2 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => openDrawer(row.id)}
                className="cursor-pointer border-t border-surface-border/60 hover:bg-surface-card/60"
              >
                <td className="px-3 py-2 text-slate-200">{row.company ?? "—"}</td>
                <td className="px-3 py-2 text-slate-300">{row.title ?? "Untitled"}</td>
                <td className="px-3 py-2 text-slate-400">{STATUS_LABELS[row.status]}</td>
                <td className="px-3 py-2 text-slate-400">
                  {row.is_remote ? "Remote" : (row.location ?? "—")}
                </td>
                <td
                  className={[
                    "px-3 py-2 tabular-nums",
                    row.staleness === "warn" ? "text-stale-warn" : "text-slate-400",
                  ].join(" ")}
                >
                  {ageLabel(row)}
                </td>
                <td className="px-3 py-2 text-slate-400">{formatDate(row.applied_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
