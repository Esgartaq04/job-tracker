import { useEffect, useState } from "react";

import type { ApplicationDetail, CleanupMeta } from "../../api/types";
import { useCleanDescription, useUpdateApplication } from "../../api/hooks";
import { useUi } from "../../lib/store";

/**
 * Three layers, most specific first: the user's edit, the AI clean-up, the raw scrape.
 * "Restore original" always works because the raw copy is immutable (README §7.3), and
 * the cleaned text is only ever the raw text with page chrome deleted — the server
 * throws away any clean-up that reworded it — so showing it by default is safe.
 */
export function DescriptionEditor({ application }: { application: ApplicationDetail }) {
  const [editing, setEditing] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const update = useUpdateApplication(application.id);
  const clean = useCleanDescription(application.id);
  const notify = useUi((state) => state.notify);

  const edited = Boolean(application.description_user);
  const hasClean = Boolean(application.description_clean);
  const shown = edited
    ? application.description_user
    : hasClean && !showOriginal
      ? application.description_clean
      : application.description_raw;

  const [draft, setDraft] = useState(shown ?? "");
  useEffect(() => setEditing(false), [application.id]);
  // Not while editing: the background clean-up can land mid-edit and change `shown`.
  useEffect(() => {
    if (!editing) setDraft(shown ?? "");
  }, [application.id, shown, editing]);

  const meta = application.extraction_meta as {
    tier?: string | null;
    confidence?: number | null;
    needs_verification?: boolean;
    cleanup?: CleanupMeta;
  };
  const cleanup = meta.cleanup;
  const canClean = !edited && !hasClean && Boolean(application.description_raw);

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
                  setDraft(shown ?? "");
                  setEditing(false);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="font-medium text-accent-ink hover:text-slate-100"
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
              {!edited && hasClean && (
                <button
                  type="button"
                  className="text-slate-400 hover:text-slate-200"
                  onClick={() => setShowOriginal((value) => !value)}
                >
                  {showOriginal ? "Show cleaned" : "Show original"}
                </button>
              )}
              {canClean && (
                <button
                  type="button"
                  disabled={clean.isPending}
                  className="text-slate-400 hover:text-slate-200 disabled:opacity-60"
                  title="Remove page clutter with AI, without rewording anything"
                  onClick={() =>
                    clean.mutate(undefined, {
                      onError: (error) => notify(error.message, "error"),
                    })
                  }
                >
                  {clean.isPending ? "Cleaning…" : "Clean up"}
                </button>
              )}
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
                  title="Discard your edits and show the description as saved"
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
          className="w-full mc-slot p-3 font-mono text-xs text-slate-200 focus:border-accent focus:outline-none"
          placeholder="Paste the description yourself…"
        />
      ) : shown ? (
        <div className="max-h-96 overflow-y-auto whitespace-pre-wrap mc-slot p-3 text-sm leading-relaxed text-slate-300">
          {shown}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-surface-border p-4 text-center text-sm text-slate-500">
          <p>Couldn&apos;t read this posting.</p>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-2 text-accent-ink hover:text-slate-100"
          >
            Paste the description yourself
          </button>
        </div>
      )}

      <p className="mt-1.5 text-[11px] text-slate-500">
        {edited
          ? "Edited by you"
          : hasClean && !showOriginal
            ? "Cleaned up by AI — page clutter removed, nothing reworded"
            : meta.tier
              ? `Extracted via ${meta.tier}`
              : "Not yet extracted"}
        {!edited && !hasClean && cleanup && cleanup.status !== "ok" && (
          <span className="ml-1" title={cleanup.reason ?? undefined}>
            · AI clean-up {cleanup.status === "rejected" ? "discarded" : "skipped"}
            {cleanup.reason ? ` (${cleanup.reason})` : ""}
          </span>
        )}
        {meta.needs_verification && (
          <span className="ml-1 text-stale-warn" title="Low-confidence extraction">
            · verify these fields
          </span>
        )}
      </p>
    </section>
  );
}
