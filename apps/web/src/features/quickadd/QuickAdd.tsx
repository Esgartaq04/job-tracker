import { useEffect, useRef, useState } from "react";

import { useIngest } from "../../api/hooks";
import { parseUrls } from "../../lib/format";
import { useUi } from "../../lib/store";

/**
 * The persistent URL field from README §7.2. Focused by `/` or ⌘K, accepts a
 * multi-line paste as a batch, and offers "mark as applied" for the "I just
 * submitted" case (README §2).
 */
export function QuickAdd() {
  const [value, setValue] = useState("");
  const [markApplied, setMarkApplied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const ingest = useIngest();
  const notify = useUi((state) => state.notify);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const typingElsewhere =
        document.activeElement instanceof HTMLInputElement ||
        document.activeElement instanceof HTMLTextAreaElement;
      if ((event.key === "/" && !typingElsewhere) || (event.key === "k" && event.metaKey)) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
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
          const duplicates = accepted.filter((entry) => entry.duplicate).length;
          if (duplicates === accepted.length) {
            notify("Already tracking that one");
          } else if (duplicates > 0) {
            notify(`Added ${accepted.length - duplicates}, ${duplicates} already tracked`);
          } else if (accepted.length > 1) {
            notify(`Queued ${accepted.length} postings`);
          }
        },
        onError: (error) => notify(error.message, "error"),
      },
    );
  }

  return (
    <div className="flex flex-1 items-center gap-2">
      <div className="relative flex-1">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">
          🔗
        </span>
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
            if (event.key === "Escape") event.currentTarget.blur();
          }}
          onPaste={(event) => {
            // Multi-line paste queues as a batch without needing Enter per line.
            const pasted = event.clipboardData.getData("text");
            if (parseUrls(pasted).length > 1) {
              event.preventDefault();
              setValue(pasted);
            }
          }}
          placeholder="Paste a job URL…   (press / to focus)"
          aria-label="Paste a job posting URL"
          className="w-full rounded-md border border-surface-border bg-surface-card py-2 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </div>

      <label className="flex select-none items-center gap-1.5 text-xs text-slate-400">
        <input
          type="checkbox"
          checked={markApplied}
          onChange={(event) => setMarkApplied(event.target.checked)}
          className="accent-accent"
        />
        applied
      </label>

      <button
        type="button"
        onClick={submit}
        disabled={ingest.isPending}
        className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white transition hover:bg-accent-muted disabled:opacity-50"
      >
        {ingest.isPending ? "Adding…" : "+"}
      </button>
    </div>
  );
}
