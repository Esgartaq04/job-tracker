import { useEffect, useState, type ReactNode } from "react";

import { api } from "../../api/client";
import {
  useCleanDescription,
  useCoverLetter,
  useEditCoverLetter,
  useGenerateCoverLetter,
} from "../../api/hooks";
import type { ApplicationDetail, CleanupMeta } from "../../api/types";
import { useUi } from "../../lib/store";

const RESUME_TYPES =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/**
 * Phase 5b. The letter is written against the cleaned description — the same rule the
 * API enforces — so this tab waits for the clean-up rather than writing a letter about
 * a page's cookie banner. The resume is uploaded for each generation and never kept.
 */
export function CoverLetter({ application }: { application: ApplicationDetail }) {
  const cleanup = (application.extraction_meta as { cleanup?: CleanupMeta }).cleanup;
  const ready = Boolean(
    application.description_user ||
      application.description_clean ||
      (application.description_raw && cleanup && cleanup.status !== "ok"),
  );

  const letter = useCoverLetter(application.id);
  const [regenerating, setRegenerating] = useState(false);

  if (!ready) return <NotReady application={application} />;
  if (letter.isLoading) {
    return <div className="h-40 animate-pulse rounded-md bg-surface-card" />;
  }
  if (!letter.data || regenerating) {
    return (
      <ResumeForm
        application={application}
        regenerating={Boolean(letter.data)}
        onDone={() => setRegenerating(false)}
      />
    );
  }
  return (
    <LetterEditor
      application={application}
      content={letter.data.content}
      onRegenerate={() => setRegenerating(true)}
    />
  );
}

function NotReady({ application }: { application: ApplicationDetail }) {
  const clean = useCleanDescription(application.id);
  const notify = useUi((state) => state.notify);

  if (!application.description_raw) {
    return (
      <Empty>
        This listing has no description yet. Add one in the Description tab, then come back to
        write a cover letter.
      </Empty>
    );
  }
  return (
    <Empty>
      <p>Waiting for the description to be cleaned up — the letter is written from the clean
        version.</p>
      <button
        type="button"
        disabled={clean.isPending}
        onClick={() => clean.mutate(undefined, { onError: (error) => notify(error.message, "error") })}
        className="mt-3 rounded-md border border-surface-border px-3 py-1.5 text-sm text-slate-200 hover:border-accent disabled:opacity-60"
      >
        {clean.isPending ? "Cleaning…" : "Clean up now"}
      </button>
    </Empty>
  );
}

function ResumeForm({
  application,
  regenerating,
  onDone,
}: {
  application: ApplicationDetail;
  regenerating: boolean;
  onDone: () => void;
}) {
  const [resume, setResume] = useState<File | null>(null);
  const [notes, setNotes] = useState("");
  const generate = useGenerateCoverLetter(application.id);

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (resume) generate.mutate({ resume, notes }, { onSuccess: onDone });
      }}
    >
      <div>
        <label htmlFor="cover-letter-resume" className="mb-1.5 block text-sm text-slate-300">
          Your resume (PDF or Word)
        </label>
        <input
          id="cover-letter-resume"
          type="file"
          accept={RESUME_TYPES}
          onChange={(event) => setResume(event.target.files?.[0] ?? null)}
          className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-surface-card file:px-3 file:py-1.5 file:text-slate-200"
        />
      </div>

      <div>
        <label htmlFor="cover-letter-notes" className="mb-1.5 block text-sm text-slate-300">
          Anything to mention? <span className="text-slate-500">(optional)</span>
        </label>
        <textarea
          id="cover-letter-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          placeholder="Referred by Ana on the payments team; available from May"
          className="w-full rounded-md border border-surface-border bg-surface-raised p-3 text-sm text-slate-200 focus:border-accent focus:outline-none"
        />
      </div>

      {generate.isError && (
        <p role="alert" className="text-sm text-stale-warn">
          {generate.error.message}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!resume || generate.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {generate.isPending
            ? "Writing your letter…"
            : regenerating
              ? "Regenerate cover letter"
              : "Generate cover letter"}
        </button>
        {regenerating && !generate.isPending && (
          <button type="button" onClick={onDone} className="text-sm text-slate-400 hover:text-slate-200">
            Cancel
          </button>
        )}
      </div>
      {generate.isPending && (
        <p className="text-xs text-slate-500">This can take up to a minute if the tracker was asleep.</p>
      )}
      <p className="text-xs text-slate-500">
        Your resume is sent to the AI to write this letter and isn&apos;t stored.
      </p>
    </form>
  );
}

function LetterEditor({
  application,
  content,
  onRegenerate,
}: {
  application: ApplicationDetail;
  content: string;
  onRegenerate: () => void;
}) {
  const [draft, setDraft] = useState(content);
  const edit = useEditCoverLetter(application.id);
  const notify = useUi((state) => state.notify);
  useEffect(() => setDraft(content), [content]);

  const dirty = draft !== content;
  const fallbackName = `Cover Letter - ${[application.company, application.title].filter(Boolean).join(" - ")}.docx`;

  return (
    <section className="space-y-3">
      <label htmlFor="cover-letter-text" className="sr-only">
        Cover letter
      </label>
      <textarea
        id="cover-letter-text"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        rows={18}
        className="w-full rounded-md border border-surface-border bg-surface-raised p-3 text-sm leading-relaxed text-slate-200 focus:border-accent focus:outline-none"
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <button
          type="button"
          disabled={!dirty || edit.isPending}
          onClick={() =>
            edit.mutate(draft, {
              onSuccess: () => notify("Cover letter saved"),
              onError: (error) => notify(error.message, "error"),
            })
          }
          className="rounded-md bg-accent px-3 py-1.5 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {edit.isPending ? "Saving…" : "Save edits"}
        </button>
        <button
          type="button"
          onClick={() =>
            navigator.clipboard
              .writeText(draft)
              .then(() => notify("Copied"))
              .catch(() => notify("Couldn't copy — select the text instead", "error"))
          }
          className="rounded-md border border-surface-border px-3 py-1.5 text-slate-200 hover:border-accent"
        >
          Copy
        </button>
        <button
          type="button"
          title={dirty ? "Save your edits first — the download is the saved letter" : undefined}
          disabled={dirty}
          onClick={() =>
            api
              .download(`/applications/${application.id}/cover-letter.docx`, fallbackName)
              .catch((error: Error) => notify(error.message, "error"))
          }
          className="rounded-md border border-surface-border px-3 py-1.5 text-slate-200 hover:border-accent disabled:opacity-50"
        >
          Download .docx
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="ml-auto rounded-md px-3 py-1.5 text-slate-400 hover:text-slate-200"
        >
          Regenerate
        </button>
      </div>
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-surface-border p-4 text-center text-sm text-slate-400">
      {children}
    </div>
  );
}
