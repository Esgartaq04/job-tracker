import { useUi } from "../../lib/store";

/** Stands in for an AI feature when the user has no usable Claude key. */
export function AddKeyPrompt({ what }: { what: string }) {
  const openAiKeyDialog = useUi((state) => state.openAiKeyDialog);
  return (
    <div className="rounded-md border border-dashed border-surface-border p-4 text-center text-sm text-slate-400">
      <p>Add your Claude API key to use {what}.</p>
      <button
        type="button"
        onClick={() => openAiKeyDialog()}
        className="mc-button mc-button-accent mt-3 px-3 py-1.5 text-sm font-medium"
      >
        Add Claude key
      </button>
    </div>
  );
}
