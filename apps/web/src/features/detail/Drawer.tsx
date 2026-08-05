import { useEffect, useRef, useState } from "react";

import {
  useAddNote,
  useApplication,
  useArchiveApplication,
  useReingest,
  useUpdateApplication,
} from "../../api/hooks";
import { STATUSES, STATUS_LABELS } from "../../api/types";
import type { AppStatus } from "../../api/types";
import { employmentLabel, faviconFor, formatDate, formatSalary } from "../../lib/format";
import { useUi } from "../../lib/store";
import { DescriptionEditor } from "./DescriptionEditor";
import { Timeline } from "./Timeline";

type TabName = "overview" | "description" | "timeline";

/**
 * Right-hand slide-over, never a route change — the board stays mounted behind it
 * (README §7.3). Focus returns to the originating card on close.
 */
export function Drawer() {
  const drawerId = useUi((state) => state.drawerId);
  const closeDrawer = useUi((state) => state.closeDrawer);
  const notify = useUi((state) => state.notify);
  const [tab, setTab] = useState<TabName>("overview");
  const [note, setNote] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<Element | null>(null);

  const { data: application, isLoading } = useApplication(drawerId);
  const update = useUpdateApplication(drawerId ?? "");
  const archive = useArchiveApplication();
  const reingest = useReingest();
  const addNote = useAddNote(drawerId ?? "");

  useEffect(() => {
    if (!drawerId) return;
    openerRef.current = document.activeElement;
    setTab("overview");
    panelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeDrawer();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      (openerRef.current as HTMLElement | null)?.focus?.();
    };
  }, [drawerId, closeDrawer]);

  if (!drawerId) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close details"
        className="flex-1 bg-black/50"
        onClick={closeDrawer}
      />

      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex h-full w-full max-w-[640px] animate-fade-in flex-col overflow-y-auto border-l border-surface-border bg-surface outline-none"
      >
        {isLoading || !application ? (
          <div className="space-y-3 p-6">
            <div className="h-6 w-2/3 animate-pulse rounded bg-surface-card" />
            <div className="h-4 w-1/3 animate-pulse rounded bg-surface-card" />
            <div className="h-40 animate-pulse rounded bg-surface-card" />
          </div>
        ) : (
          <>
            <header className="border-b border-surface-border p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2">
                  {faviconFor(application) && (
                    <img
                      src={faviconFor(application) as string}
                      alt=""
                      className="mt-1 h-5 w-5 rounded"
                    />
                  )}
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-medium text-slate-100">
                      {application.company ?? "Unknown company"}
                    </h2>
                    <p className="truncate text-sm text-slate-400">
                      {application.title ?? "Untitled"}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={closeDrawer}
                  className="rounded p-1 text-slate-400 hover:text-slate-100"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              <p className="mt-2 text-xs text-slate-500">
                {[
                  application.is_remote ? "Remote" : application.location,
                  employmentLabel(application.employment_type),
                  application.applied_at
                    ? `Applied ${formatDate(application.applied_at)}`
                    : `Saved ${formatDate(application.saved_at)}`,
                  formatSalary(application),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor="status-select">
                  Status
                </label>
                <select
                  id="status-select"
                  value={application.status}
                  onChange={(event) =>
                    update.mutate(
                      { status: event.target.value as AppStatus },
                      {
                        onError: () => notify("Couldn't change the status", "error"),
                      },
                    )
                  }
                  className="rounded-md border border-surface-border bg-surface-card px-2 py-1.5 text-sm text-slate-200 focus:border-accent focus:outline-none"
                >
                  {STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {STATUS_LABELS[status]}
                    </option>
                  ))}
                </select>

                {application.source_url.startsWith("http") && (
                  <a
                    href={application.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="rounded-md border border-surface-border px-2 py-1.5 text-sm text-slate-300 hover:border-accent hover:text-slate-100"
                  >
                    Open posting ↗
                  </a>
                )}

                <button
                  type="button"
                  onClick={() => reingest.mutate(application.id)}
                  className="rounded-md border border-surface-border px-2 py-1.5 text-sm text-slate-300 hover:border-accent hover:text-slate-100"
                  title="Run the extraction pipeline again"
                >
                  Re-extract
                </button>

                <button
                  type="button"
                  onClick={() => {
                    archive.mutate(application.id);
                    closeDrawer();
                  }}
                  className="ml-auto rounded-md px-2 py-1.5 text-sm text-slate-500 hover:text-stale-warn"
                >
                  Archive
                </button>
              </div>
            </header>

            <nav className="flex gap-1 border-b border-surface-border px-4">
              {(["overview", "description", "timeline"] as TabName[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setTab(name)}
                  className={[
                    "px-3 py-2 text-sm capitalize transition",
                    tab === name
                      ? "border-b-2 border-accent text-slate-100"
                      : "text-slate-400 hover:text-slate-200",
                  ].join(" ")}
                >
                  {name}
                </button>
              ))}
            </nav>

            <div className="flex-1 space-y-6 p-5">
              {tab === "overview" && (
                <>
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <Field label="Status" value={STATUS_LABELS[application.status]} />
                    <Field label="Saved" value={formatDate(application.saved_at)} />
                    <Field label="Applied" value={formatDate(application.applied_at)} />
                    <Field label="Posted" value={formatDate(application.posted_at)} />
                    <Field label="Source" value={application.ats_vendor ?? application.source_host ?? "—"} />
                    <Field label="Req ID" value={application.req_id ?? "—"} />
                  </dl>

                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Tags
                    </h3>
                    <input
                      defaultValue={application.tags.map((tag) => tag.name).join(", ")}
                      onBlur={(event) =>
                        update.mutate({
                          tags: event.target.value
                            .split(",")
                            .map((value) => value.trim())
                            .filter(Boolean),
                        })
                      }
                      placeholder="referral, summer-2027"
                      className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:border-accent focus:outline-none"
                    />
                  </section>

                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Notes
                    </h3>
                    {application.notes && (
                      <pre className="mb-2 whitespace-pre-wrap rounded-md border border-surface-border bg-surface-raised p-3 text-sm text-slate-300">
                        {application.notes}
                      </pre>
                    )}
                    <div className="flex gap-2">
                      <input
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && note.trim()) {
                            addNote.mutate(note.trim());
                            setNote("");
                          }
                        }}
                        placeholder="Referred by Andres — team is on Go"
                        className="flex-1 rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:border-accent focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          if (!note.trim()) return;
                          addNote.mutate(note.trim());
                          setNote("");
                        }}
                        className="rounded-md bg-surface-card px-3 text-sm text-slate-200 hover:bg-surface-border"
                      >
                        Add
                      </button>
                    </div>
                  </section>

                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Next action
                    </h3>
                    <input
                      type="date"
                      value={application.next_action_at?.slice(0, 10) ?? ""}
                      onChange={(event) =>
                        update.mutate({
                          next_action_at: event.target.value
                            ? new Date(`${event.target.value}T09:00:00`).toISOString()
                            : null,
                        })
                      }
                      className="rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:border-accent focus:outline-none"
                    />
                  </section>
                </>
              )}

              {tab === "description" && <DescriptionEditor application={application} />}
              {tab === "timeline" && <Timeline events={application.events} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-slate-200">{value}</dd>
    </div>
  );
}
