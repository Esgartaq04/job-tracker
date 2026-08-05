import { useEffect, useState } from "react";

import { useIngest } from "../../api/hooks";
import { parseUrls } from "../../lib/format";
import { useUi } from "../../lib/store";

/**
 * On mobile, quick-add is a floating button that opens a sheet (README §7.5) — a
 * persistent URL bar in the header would eat a third of the viewport.
 *
 * It also handles the PWA share target: when the OS share sheet sends a URL to the
 * app, we land on `/?share=…` and open pre-filled, so sharing a posting from the
 * LinkedIn app is two taps.
 */
export function QuickAddSheet() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [markApplied, setMarkApplied] = useState(false);
  const ingest = useIngest();
  const notify = useUi((state) => state.notify);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // Android sends `text`, iOS tends to send `url`; `title` is the fallback.
    const shared = ["url", "text", "title"]
      .map((key) => params.get(key))
      .find((candidate) => candidate && parseUrls(candidate).length > 0);

    if (shared) {
      setValue(parseUrls(shared)[0]);
      setOpen(true);
      // Drop the query string so a refresh doesn't re-open the sheet.
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  function submit() {
    const urls = parseUrls(value);
    if (urls.length === 0) {
      notify("That doesn't look like a job posting URL", "error");
      return;
    }
    ingest.mutate(
      { urls, markAsApplied: markApplied },
      {
        onSuccess: (accepted) => {
          setValue("");
          setOpen(false);
          const duplicates = accepted.filter((entry) => entry.duplicate).length;
          notify(
            duplicates === accepted.length
              ? "Already tracking that one"
              : `Added ${accepted.length - duplicates}`,
          );
        },
        onError: (error) => notify(error.message, "error"),
      },
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Add a job posting"
        className="fixed bottom-5 right-5 z-30 h-14 w-14 rounded-full bg-accent text-2xl text-white shadow-lg transition active:scale-95 md:hidden"
      >
        +
      </button>

      {open && (
        <div className="fixed inset-0 z-40 flex items-end md:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
          />
          <div className="relative w-full animate-fade-in rounded-t-2xl border-t border-surface-border bg-surface-raised p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <h2 className="mb-3 text-sm font-medium text-slate-200">Track a posting</h2>

            <input
              autoFocus
              value={value}
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
              inputMode="url"
              placeholder="Paste a job URL…"
              aria-label="Job posting URL"
              className="w-full rounded-md border border-surface-border bg-surface-card px-3 py-3 text-base text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none"
            />

            <label className="mt-3 flex items-center gap-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={markApplied}
                onChange={(event) => setMarkApplied(event.target.checked)}
                className="h-4 w-4 accent-accent"
              />
              I already applied
            </label>

            <button
              type="button"
              onClick={submit}
              disabled={ingest.isPending}
              className="mt-4 w-full rounded-md bg-accent py-3 text-sm font-medium text-white disabled:opacity-50"
            >
              {ingest.isPending ? "Adding…" : "Add to board"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
