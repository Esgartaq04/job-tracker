import { useEffect, useState } from "react";

import type { ApplicationDetail } from "../../api/types";
import { useUpdateApplication } from "../../api/hooks";

/**
 * `description_user` shadows `description_raw`; "Restore original" always works
 * because the raw copy is immutable (README §7.3). A subtle line records which
 * tier produced the text — useful when a field looks wrong.
 */
export function DescriptionEditor({ application }: { application: ApplicationDetail }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(application.description ?? "");
  const update = useUpdateApplication(application.id);

  useEffect(() => {
    setDraft(application.description ?? "");
  }, [application.id, application.description]);

  const meta = application.extraction_meta as {
    tier?: string | null;
    confidence?: number | null;
    needs_verification?: boolean;
  };
  const edited = Boolean(application.description_user);

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Description
        </h3>
        <div className="flex gap-2 text-xs">
          {editing ? (
            <>
              <button
                type="button"
                className="text-slate-400 hover:text-slate-200"
                onClick={() => {
                  setDraft(application.description ?? "");
                  setEditing(false);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="font-medium text-accent hover:text-indigo-300"
                onClick={() => {
                  update.mutate({ description_user: draft });
                  setEditing(false);
                }}
              >
                Save
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="text-slate-400 hover:text-slate-200"
                onClick={() => setEditing(true)}
              >
                Edit
              </button>
              {edited && application.description_raw && (
                <button
                  type="button"
                  className="text-slate-400 hover:text-slate-200"
                  onClick={() => update.mutate({ description_user: null })}
                  title="Discard your edits and show the archived original"
                >
                  Restore original
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {editing ? (
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={16}
          className="w-full rounded-md border border-surface-border bg-surface-raised p-3 font-mono text-xs text-slate-200 focus:border-accent focus:outline-none"
          placeholder="Paste the description yourself…"
        />
      ) : application.description ? (
        <div className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border border-surface-border bg-surface-raised p-3 text-sm leading-relaxed text-slate-300">
          {application.description}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-surface-border p-4 text-center text-sm text-slate-500">
          <p>Couldn&apos;t read this posting.</p>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-2 text-accent hover:text-indigo-300"
          >
            Paste the description yourself
          </button>
        </div>
      )}

      <p className="mt-1.5 text-[11px] text-slate-500">
        {edited
          ? "Edited by you"
          : meta.tier
            ? `Extracted via ${meta.tier}`
            : "Not yet extracted"}
        {meta.needs_verification && (
          <span className="ml-1 text-stale-warn" title="Low-confidence extraction">
            · verify these fields
          </span>
        )}
      </p>
    </section>
  );
}
