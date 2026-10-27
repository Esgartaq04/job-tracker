import { useEffect, useRef, useState, type FormEvent } from "react";

import { useAiKey, useRemoveAiKey, useSaveAiKey } from "../../api/hooks";
import { useUi } from "../../lib/store";

const KEYS_URL = "https://console.anthropic.com/settings/keys";

/**
 * Save, replace or remove the user's own Claude API key. The key is write-only: the
 * server answers with the last four characters and nothing else, so that is all this ever
 * shows. The panel mounts only while the dialog is open, so a half-typed key is dropped
 * the moment it closes.
 */
export function AiKeyDialog() {
  const open = useUi((state) => state.aiKeyDialogOpen);
  return open ? <AiKeyPanel /> : null;
}

function AiKeyPanel() {
  const close = useUi((state) => state.closeAiKeyDialog);
  const { data: saved } = useAiKey();
  const { save, isPending: saving, error: saveError } = useSaveAiKey();
  const remove = useRemoveAiKey();
  // The key being typed lives here and nowhere else: not the store, not the query cache.
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState(false);
  // Captured while rendering, before autofocus moves focus into the dialog.
  const [opener] = useState(() => document.activeElement);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (opener?.isConnected) (opener as HTMLElement).focus?.();
    };
  }, [close, opener]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const apiKey = draft.trim();
    if (!apiKey || saving) return;
    // Empty the field before the request goes out: from here on the key exists only as
    // this call's argument. A failed save means pasting it again, which beats leaving a
    // credential sitting in a text box.
    setDraft("");
    save(apiKey).catch(() => undefined); // the hook keeps the error for us to show
  }

  function confirmRemove() {
    remove.mutate(undefined, { onSuccess: () => setConfirming(false) });
  }

  const hasKey = saved?.has_key ?? false;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-key-title"
    >
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 cursor-default bg-black/60"
        onClick={close}
      />

      <div
        className="mc-panel relative max-h-full w-full max-w-md animate-fade-in overflow-y-auto bg-surface p-5"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id="ai-key-title" className="text-lg font-medium text-slate-100">
            Connect Claude
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close dialog"
            className="rounded p-1 text-slate-400 hover:text-slate-100"
          >
            ✕
          </button>
        </div>

        <p className="mt-2 text-sm text-slate-400">
          Powers link auto-fill, description clean-up, cover letters and extension autofill.
          Stored encrypted; never shown again.
        </p>

        {hasKey && (
          <div className="mc-slot mt-4 px-3 py-2 text-sm">
            {saved?.hint && (
              <p className="text-slate-200">
                Saved key: <span className="font-mono">{saved.hint}</span>
              </p>
            )}
            {saved?.status === "rejected" && (
              <p className="mt-1 text-stale-warn">Claude rejected this key — paste a new one.</p>
            )}
          </div>
        )}

        <form onSubmit={submit} className="mt-4">
          <label htmlFor="ai-key-input" className="block text-sm text-slate-300">
            Claude API key
          </label>
          <input
            id="ai-key-input"
            ref={inputRef}
            type="password"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={hasKey ? "Paste a new key to replace it" : "sk-ant-…"}
            className="mc-slot mt-1 w-full px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none"
          />

          <p className="mt-2 text-xs text-slate-500">
            Get one at{" "}
            <a
              href={KEYS_URL}
              target="_blank"
              rel="noreferrer"
              className="text-accent-ink underline"
            >
              console.anthropic.com
            </a>
            . Tip: make a separate key for this app with a monthly spend limit.
          </p>

          {saveError && (
            <p role="alert" className="mt-3 text-sm text-stale-warn">
              {saveError.message}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={!draft.trim() || saving}
              className="mc-button mc-button-accent px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {saving ? "Checking…" : "Save key"}
            </button>

            {hasKey && !confirming && (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="mc-button ml-auto px-4 py-2 text-sm"
              >
                Remove key
              </button>
            )}
          </div>
        </form>

        {hasKey && confirming && (
          <div className="mc-slot mt-4 p-3">
            <p className="text-sm text-slate-200">
              Remove your saved key? AI features stay off until you add another.
            </p>
            {remove.error && (
              <p role="alert" className="mt-2 text-sm text-stale-warn">
                {remove.error.message}
              </p>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={confirmRemove}
                disabled={remove.isPending}
                className="mc-button mc-button-accent px-4 py-2 text-sm font-medium disabled:opacity-50"
              >
                Yes, remove it
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={remove.isPending}
                className="mc-button px-4 py-2 text-sm disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
